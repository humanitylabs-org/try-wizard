import AppKit
import CoreGraphics
import Darwin
import IOKit.ps

/// Wizard OS updates on a Mac. The App Manager in the VM keeps the owner's choice (Automatic / Ask me, channel) but
/// starts nothing by itself here (the guest's /etc/wizard/updates-by-host). The Mac starts every update, and only
/// after a copy of the VM disk:
///
///   check -> stop Wizard OS -> clone disk.img (APFS, instant) -> start -> `wam updates --apply[-if-auto]`
///   -> wait for the installer -> installed == target and the window answers -> keep the copy a day, then delete it
///   anything else -> stop -> put the copy back -> start, and say so in one line.
///
/// Ask me (the default) never updates by itself: the owner sees "WizardOS x is ready" on every device and taps
/// Update now (confirmed there), or updates any time from Settings or this menu.
/// Automatic (the owner's choice in Settings): only at night (01:00-05:00 Mac time), when the App Manager says
/// Automatic would install now (channel, promotion, the agent not working), the Mac is on power, untouched for 15
/// minutes and not recording; then a 5-minute heads-up on every device (Update now / Not tonight), cancelled if
/// anyone comes to the Mac. Update now runs the same steps at once.
/// The journal (os-updates/journal.json) survives a Host restart, so an interrupted update is finished or undone
/// on the next launch. Wizard.app reads it to show progress and the result.
final class OSUpdates {
    static var dir: URL { WizardShared.supportDir.appendingPathComponent("os-updates", isDirectory: true) }
    static var journalURL: URL { dir.appendingPathComponent("journal.json") }
    static var copyURL: URL { dir.appendingPathComponent("disk-before-update.img") }
    static var activityURL: URL { dir.appendingPathComponent("app-activity.json") }
    static var diskURL: URL { WizardShared.osDir.appendingPathComponent("disk.img") }

    static let idleNeeded: TimeInterval = 15 * 60
    static let keepCopy: TimeInterval = 24 * 3600
    static let installLimit: TimeInterval = 90 * 60
    static let windowLimit: TimeInterval = 10 * 60
    /// The copy shares every block with disk.img until the update writes; the update rewrites a few GB of images.
    static let freeNeeded: Int64 = 12_000_000_000
    static let active: Set<String> = ["stopping", "copying", "booting", "updating", "verifying", "restoring"]

    private let vm: VMController
    /// The Host's own update work (a Wizard.app update or guest patch) that must not overlap this one.
    var otherWork: () -> Bool = { false }
    var onChange: () -> Void = {}
    private(set) var busy = false
    private var lastAutoCheck = Date.distantPast
    private var activity: NSObjectProtocol?
    private var timer: Timer?

    init(vm: VMController) { self.vm = vm }

    // MARK: journal

    static func journal() -> [String: Any] { WizardUpdate.json(journalURL) }
    private func save(_ changes: [String: Any]) {
        var j = Self.journal()
        for (k, v) in changes { j[k] = v }
        j["updatedAt"] = Date().timeIntervalSince1970
        try? FileManager.default.createDirectory(at: Self.dir, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        if let d = try? JSONSerialization.data(withJSONObject: j, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: Self.journalURL, options: .atomic)
        }
        onChange()
    }
    private func phase(_ p: String) { log("Wizard OS update: \(p)"); save(["phase": p]) }

    /// One line for the menu bar while an update runs.
    var statusText: String? {
        let j = Self.journal()
        guard busy, let p = j["phase"] as? String, Self.active.contains(p) else { return nil }
        let to = (j["target"] as? String).map { " to \($0)" } ?? ""
        return p == "restoring" ? "Wizard OS update didn't finish — restoring the copy…" : "Updating Wizard OS\(to)…"
    }

    // MARK: start-up

    /// Before the first boot: an update cut short while putting the copy back must finish that first.
    func prepareBoot() {
        let j = Self.journal()
        guard j["phase"] as? String == "restoring" else { return }
        if FileManager.default.fileExists(atPath: Self.copyURL.path) {
            if rename(Self.copyURL.path, Self.diskURL.path) == 0 {
                log("Wizard OS update: put the copy back after a restart")
                finish(result: "restored", reason: (j["reason"] as? String) ?? "The update did not finish.")
            } else {
                log("Wizard OS update: could not put the copy back (\(String(cString: strerror(errno))))")
            }
        } else {
            finish(result: "restored", reason: (j["reason"] as? String) ?? "The update did not finish.")
        }
    }

    func start() {
        resume()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.tick() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in self?.tick() }
    }

    private func resume() {
        let j = Self.journal()
        switch j["phase"] as? String {
        case "stopping", "copying", "booting":
            // Nothing was installed yet: the disk is the one from before.
            try? FileManager.default.removeItem(at: Self.copyURL)
            finish(result: "skipped", reason: "Wizard stopped before the update started; nothing changed.")
        case "updating", "verifying":
            busy = true; begin()
            log("Wizard OS update: resuming after a Host restart")
            whenRunning(limit: Self.windowLimit) { [weak self] ok in
                guard let self else { return }
                guard ok else { self.restore("Wizard OS did not start again during the update."); return }
                self.monitor(started: (j["updateStartedAt"] as? Double).map { Date(timeIntervalSince1970: $0) } ?? Date())
            }
        default: break
        }
    }

    // MARK: the checks

    private var blocked: String? {
        if busy { return "an update is running" }
        if otherWork() { return "Wizard is updating itself" }
        if vm.state != .running { return "Wizard OS is not running" }
        if WizardShared.coldBootstrapToken != nil || WizardShared.guestUpdatePayload != nil { return "an upgrade is open" }
        let done: Set<String> = ["guest-activated", "guest-rolled-back", "install-failed", "native-activated"]
        if let p = WizardUpdate.json(WizardUpdate.journal)["phase"] as? String, !done.contains(p) { return "an upgrade is open" }
        return nil
    }

    private func tick() {
        dropOldCopy()
        guard blocked == nil else { return }
        // What the owner said from any device: Update now (Settings, confirmed there) or Not tonight (the heads-up).
        vm.control("update-inbox") { [weak self] data in
            guard let self, self.blocked == nil else { return }
            let inbox = Self.object(data) ?? [:]
            if let req = inbox["request"] as? [String: Any], let target = req["target"] as? String {
                log("Wizard OS update: Update now requested for \(target)")
                self.clearHeadsUp()
                self.run(kind: "manual", target: target)
                return
            }
            if inbox["postponed"] is [String: Any] {
                self.vm.control("update-postpone-clear") { _ in }
                self.postponedNight = Self.nightKey(Date())
                if self.headsUp != nil { log("Wizard OS update: Not tonight"); self.clearHeadsUp() }
            }
            if self.headsUp != nil { self.headsUpTick() } else { self.autoTick() }
        }
    }

    // MARK: Automatic: only at night, only on Automatic, with a 5-minute heads-up

    /// Automatic updates start between 01:00 and 05:00 Mac time (the heads-up and the update both inside it).
    static let nightStart = 1, nightEnd = 5
    static let headsUpLead: TimeInterval = 5 * 60
    static let autoEveryAtNight: TimeInterval = 10 * 60
    static func atNight(_ d: Date) -> Bool {
        let h = Calendar.current.component(.hour, from: d)
        return h >= nightStart && h < nightEnd
    }
    /// One key per night (the date the night's evening began), for Not tonight.
    static func nightKey(_ d: Date) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d.addingTimeInterval(-12 * 3600))
    }
    private var postponedNight: String? {
        get { Self.journal()["postponedNight"] as? String }
        set { save(["postponedNight": newValue ?? NSNull()]) }
    }
    private var headsUp: (target: String, at: Date, since: Date)?

    private func autoTick() {
        let now = Date()
        guard Self.atNight(now), Self.atNight(now.addingTimeInterval(Self.headsUpLead + 60)),
              postponedNight != Self.nightKey(now),
              now.timeIntervalSince(lastAutoCheck) >= Self.autoEveryAtNight else { return }
        lastAutoCheck = now
        if let why = Self.notNow() { log("Wizard OS update: not now (\(why))"); return }
        vm.control("update-check", timeout: 120) { [weak self] data in
            guard let self, self.blocked == nil, self.headsUp == nil, let st = Self.object(data) else { return }
            // Ask me never updates by itself: only an owner who chose Automatic gets a night update.
            guard st["mode"] as? String == "auto", st["due"] as? Bool == true, let target = st["latest"] as? String,
                  target.range(of: #"^[0-9]+\.[0-9]+\.[0-9]+$"#, options: .regularExpression) != nil else {
                if let skipped = st["skipped"] as? String { log("Wizard OS update: Automatic skipped (\(skipped))") }
                return
            }
            if let failed = Self.journal()["failedTarget"] as? String, failed == target { return }   // one try per release
            if let why = Self.notNow() { log("Wizard OS update: not now (\(why))"); return }
            self.startHeadsUp(target)
        }
    }

    /// Every device shows "WizardOS updates in 5 minutes · Update now · Not tonight" (the App Manager's
    /// host_headsup); the Mac starts the update when the time is up and nobody said no.
    private func startHeadsUp(_ target: String) {
        let at = Date().addingTimeInterval(Self.headsUpLead)
        headsUp = (target, at, Date())
        log("Wizard OS update: heads-up, Automatic installs \(target) at \(at)")
        vm.control("update-headsup \(Int(at.timeIntervalSince1970)) \(target)") { _ in }
        // Check every 15 s from here, not only on the minute.
        for i in 1...Int(Self.headsUpLead / 15) + 2 {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 15) { [weak self] in
                guard let self, self.headsUp != nil, !self.busy else { return }
                self.tick()
            }
        }
    }

    private func clearHeadsUp() {
        guard headsUp != nil else { return }
        headsUp = nil
        vm.control("update-headsup-clear") { _ in }
    }

    private func headsUpTick() {
        guard let h = headsUp else { return }
        let idle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: ~0)!)
        if idle < Date().timeIntervalSince(h.since) || Self.appRecording || !Self.onACPower {
            // Someone came to the Mac (or it started recording, or left power): not now; maybe later tonight.
            log("Wizard OS update: heads-up cancelled (the Mac is in use)")
            clearHeadsUp(); lastAutoCheck = Date(); return
        }
        guard Date() >= h.at else { return }
        vm.control("update-check", timeout: 120) { [weak self] data in
            guard let self, let cur = self.headsUp, cur.target == h.target else { return }
            let st = Self.object(data) ?? [:]
            guard self.blocked == nil, st["mode"] as? String == "auto", st["due"] as? Bool == true,
                  st["latest"] as? String == h.target else {
                log("Wizard OS update: heads-up ended without an update (\(st["skipped"] as? String ?? "no longer due"))")
                self.clearHeadsUp(); return
            }
            self.headsUp = nil   // `wam updates --apply-if-auto` clears the guest's heads-up when it starts
            self.run(kind: "auto", target: h.target)
        }
    }

    /// Automatic waits for a Mac nobody is using: on power, untouched for 15 minutes, not recording.
    static func notNow() -> String? {
        if !onACPower { return "on battery" }
        let idle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: ~0)!)
        if idle < idleNeeded { return "in use" }
        if appRecording { return "recording" }
        return nil
    }

    static var onACPower: Bool {
        guard let info = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let type = IOPSGetProvidingPowerSourceType(info)?.takeUnretainedValue() else { return true }
        return (type as String) == kIOPMACPowerKey
    }

    /// Wizard.app writes app-activity.json every 20 s while it runs (meeting or voice recording).
    static var appRecording: Bool {
        let a = WizardUpdate.json(activityURL)
        guard let pid = a["pid"] as? Int32, kill(pid, 0) == 0,
              let at = a["at"] as? Double, Date().timeIntervalSince1970 - at < 90 else { return false }
        return a["recording"] as? Bool ?? true
    }

    private static func object(_ data: Data?) -> [String: Any]? {
        guard let data, let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return o
    }

    // MARK: Update now from the Host menu (shown while Wizard.app is closed)

    func updateNowFromMenu() {
        if let why = blocked { alert("Wizard OS can't update right now", "\(why.prefix(1).uppercased())\(why.dropFirst()).") ; return }
        vm.control("update-status", timeout: 120) { [weak self] data in
            guard let self else { return }
            guard let st = Self.object(data), st["error"] == nil else {
                self.alert("Couldn't check for a Wizard OS update", "The App Manager in Wizard OS didn't answer. Try again in a minute.")
                return
            }
            let installed = st["installed"] as? String ?? "unknown"
            guard st["update_available"] as? Bool == true, st["installing"] as? Bool != true,
                  let target = st["latest"] as? String else {
                self.alert("Wizard OS is up to date", "This Wizard runs \(installed).")
                return
            }
            NSApp.activate(ignoringOtherApps: true)
            let a = NSAlert()
            a.messageText = "Update Wizard OS to \(target)?"
            a.informativeText = "Wizard saves a copy of Wizard OS first and puts it back if the update fails. Wizard OS restarts once and is away for 10–20 minutes. You can also update any time in Settings."
            a.addButton(withTitle: "Update"); a.addButton(withTitle: "Cancel")
            if a.runModal() == .alertFirstButtonReturn { self.run(kind: "manual", target: target) }
        }
    }

    private func alert(_ title: String, _ text: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert(); a.messageText = title; a.informativeText = text; a.runModal()
    }

    // MARK: the run

    private func run(kind: String, target: String) {
        guard blocked == nil else { return }
        if let free = VMController.freeBytes(), free < Self.freeNeeded {
            let reason = String(format: "Not enough free space on this Mac to keep a copy of Wizard OS during the update (%.0f GB free, needs %.0f GB).",
                                Double(free) / 1e9, Double(Self.freeNeeded) / 1e9)
            log("Wizard OS update: \(reason)")
            save(["id": UUID().uuidString, "kind": kind, "target": target, "phase": "done", "result": "skipped",
                  "reason": reason, "finishedAt": Date().timeIntervalSince1970])
            if kind == "manual" { vm.control("update-request-clear") { _ in } }
            return
        }
        busy = true; begin()
        let old = Self.journal()
        var fresh: [String: Any] = ["id": UUID().uuidString, "kind": kind, "target": target,
                                    "startedAt": Date().timeIntervalSince1970]
        if let f = old["failedTarget"] { fresh["failedTarget"] = f }
        try? FileManager.default.removeItem(at: Self.journalURL)
        save(fresh)
        vm.control("update-status", timeout: 120) { [weak self] data in
            guard let self else { return }
            let st = Self.object(data) ?? [:]
            if let installed = st["installed"] as? String { self.save(["from": installed]) }
            // The request is taken now, whatever happens next (an App Manager without request_host_apply's
            // clean-up must not start this again after it finishes).
            if kind == "manual" { self.vm.control("update-request-clear") { _ in } }
            guard st["update_available"] as? Bool == true, st["installing"] as? Bool != true else {
                self.finish(result: "skipped", reason: st["installing"] as? Bool == true
                            ? "An update is already running in Wizard OS."
                            : st.isEmpty ? "The App Manager in Wizard OS didn't answer." : "Wizard OS is already up to date.")
                return
            }
            self.phase("stopping")
            self.vm.stop(forceOnTimeout: false, onTimeout: { [weak self] in
                // Wizard OS didn't shut down cleanly: no copy of a disk that may be mid-write, no update.
                self?.abandon("Wizard OS didn't shut down cleanly, so nothing was updated.")
            }) { [weak self] in self?.copyAndBoot(kind: kind) }
        }
    }

    private func copyAndBoot(kind: String) {
        if otherWork() {   // Wizard is quitting: leave Wizard OS stopped on its unchanged disk
            finish(result: "skipped", reason: "Wizard quit before the update started; nothing changed.")
            return
        }
        phase("copying")
        let started = Date()
        try? FileManager.default.removeItem(at: Self.copyURL)   // the copy kept from the last update
        guard clonefile(Self.diskURL.path, Self.copyURL.path, 0) == 0 else {
            let why = String(cString: strerror(errno))
            vm.start()
            abandon("Couldn't copy Wizard OS before the update (\(why)), so nothing was updated.")
            return
        }
        log(String(format: "Wizard OS update: disk copied in %.1fs", Date().timeIntervalSince(started)))
        phase("booting")
        vm.start()
        whenRunning(limit: Self.windowLimit) { [weak self] ok in
            guard let self else { return }
            guard ok else {
                // The copy is the same disk; putting it back changes nothing. Leave Wizard OS as it is.
                try? FileManager.default.removeItem(at: Self.copyURL)
                self.finish(result: "failed", reason: "Wizard OS did not start after the copy; nothing was updated.")
                return
            }
            self.phase("updating")
            self.save(["updateStartedAt": Date().timeIntervalSince1970])
            self.vm.control(kind == "auto" ? "update-auto" : "update-now", timeout: 600) { [weak self] data in
                guard let self else { return }
                let res = Self.object(data) ?? [:]
                guard res["started"] as? Bool == true else {
                    try? FileManager.default.removeItem(at: Self.copyURL)
                    let why = (res["error"] as? String) ?? (res["note"] as? String) ?? (res["skipped"] as? String)
                        ?? (res["update_available"] as? Bool == false ? "already up to date" : "the App Manager didn't start it")
                    self.finish(result: "skipped", reason: "The update didn't start: \(why).")
                    return
                }
                if let quick = res["quick"] as? Bool { self.save(["quick": quick]) }
                self.monitor(started: Date())
            }
        }
    }

    /// Poll the App Manager until the installer is done; then read back what is installed and served.
    private func monitor(started: Date) {
        var misses = 0
        var lastSeen = Date()
        func poll() {
            if Date().timeIntervalSince(started) > Self.installLimit {
                restore("The update was still running after \(Int(Self.installLimit / 60)) minutes."); return
            }
            if vm.state == .error || vm.state == .stopped || vm.state == .notInstalled {
                restore("Wizard OS stopped during the update."); return
            }
            vm.control("update-status", timeout: 120) { [weak self] data in
                guard let self else { return }
                guard let st = Self.object(data), st["error"] == nil else {
                    misses += 1
                    if Date().timeIntervalSince(lastSeen) > Self.windowLimit {
                        self.restore("Wizard OS stopped answering during the update."); return
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 15, execute: poll); return
                }
                misses = 0; lastSeen = Date()
                if st["installing"] as? Bool == true {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 15, execute: poll); return
                }
                self.verify(st)
            }
        }
        poll()
    }

    private func verify(_ st: [String: Any]) {
        phase("verifying")
        let target = Self.journal()["target"] as? String
        let installed = st["installed"] as? String
        if st["failed"] as? Bool == true || st["interrupted"] as? Bool == true || installed == nil || installed != target {
            let why = (st["failure_reason"] as? String).map { "The installer said: \($0)" }
                ?? (st["interrupted"] as? Bool == true ? "The installer stopped before it finished." : nil)
                ?? "Wizard OS reports \(installed ?? "no installed release") instead of \(target ?? "the new release")."
            restore(why); return
        }
        // The window must answer on the new release, not only the installer's read-back.
        let deadline = Date().addingTimeInterval(5 * 60)
        func probe() {
            var req = URLRequest(url: WizardShared.localUXHealthURL); req.timeoutInterval = 5
            req.cachePolicy = .reloadIgnoringLocalCacheData
            URLSession.shared.dataTask(with: req) { [weak self] _, resp, _ in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if (resp as? HTTPURLResponse)?.statusCode == 200 {
                        log("Wizard OS update: \(installed ?? "?") installed and answering")
                        self.save(["copyKeptUntil": Date().addingTimeInterval(Self.keepCopy).timeIntervalSince1970,
                                   "failedTarget": NSNull()])
                        self.finish(result: "ok", reason: nil)
                    } else if Date() > deadline {
                        self.restore("Wizard \(installed ?? "") was installed, but the Wizard window didn't answer.")
                    } else {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 10, execute: probe)
                    }
                }
            }.resume()
        }
        probe()
    }

    /// The update failed: keep the installer's log on the Mac, stop, put the copy back, start.
    private func restore(_ reason: String) {
        log("Wizard OS update failed: \(reason)")
        save(["reason": reason, "failedTarget": Self.journal()["target"] ?? NSNull()])
        func putBack() {
            // A stop already under way (Wizard OS shutting itself down) must finish first.
            if vm.state == .stopping || vm.state == .starting {
                DispatchQueue.main.asyncAfter(deadline: .now() + 5) { putBack() }; return
            }
            self.phase("restoring")
            self.vm.stop(forceOnTimeout: true, completion: { [weak self] in
                guard let self else { return }
                guard rename(Self.copyURL.path, Self.diskURL.path) == 0 else {
                    let why = String(cString: strerror(errno))
                    log("Wizard OS update: could not put the copy back (\(why)); copy kept at \(Self.copyURL.path)")
                    self.vm.start()
                    self.finish(result: "failed", reason: "\(reason) The copy could not be put back (\(why)); it is kept.")
                    return
                }
                log("Wizard OS update: copy put back")
                self.vm.start()
                self.finish(result: "restored", reason: reason)
            })
        }
        guard vm.state == .running else { putBack(); return }
        vm.control("update-log", timeout: 30) { data in
            if let data {
                let f = WizardShared.logsDir.appendingPathComponent("wizard-os-update-failed.log")
                try? data.write(to: f, options: .atomic)
            }
            putBack()
        }
    }

    /// Nothing was installed (the run stopped before the copy or before the update started).
    private func abandon(_ reason: String) {
        log("Wizard OS update: \(reason)")
        try? FileManager.default.removeItem(at: Self.copyURL)
        if vm.state == .stopped { vm.start() }
        else if vm.state == .stopping {
            // A late clean stop after the timeout: start again once it is down.
            func wait(_ n: Int) {
                if vm.state == .stopped { vm.start(); return }
                if n > 0 { DispatchQueue.main.asyncAfter(deadline: .now() + 5) { wait(n - 1) } }
            }
            wait(60)
        }
        finish(result: "failed", reason: reason)
    }

    private func finish(result: String, reason: String?) {
        var changes: [String: Any] = ["phase": "done", "result": result, "finishedAt": Date().timeIntervalSince1970]
        changes["reason"] = reason ?? NSNull()
        save(changes)
        log("Wizard OS update finished: \(result)\(reason.map { " — \($0)" } ?? "")")
        busy = false
        end()
        onChange()
    }

    private func dropOldCopy() {
        guard !busy, FileManager.default.fileExists(atPath: Self.copyURL.path) else { return }
        let j = Self.journal()
        let until = j["copyKeptUntil"] as? Double ?? 0
        if j["phase"] as? String == "done", Date().timeIntervalSince1970 > until {
            try? FileManager.default.removeItem(at: Self.copyURL)
            log("Wizard OS update: dropped the copy from before the last update")
            save(["copyKeptUntil": NSNull()])
        }
    }

    private func whenRunning(limit: TimeInterval, _ done: @escaping (Bool) -> Void) {
        let deadline = Date().addingTimeInterval(limit)
        func check() {
            if vm.state == .running { done(true); return }
            if vm.state == .error || Date() > deadline { done(false); return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 2, execute: check)
        }
        check()
    }

    /// Keep the Mac awake (not the display) while Wizard OS updates.
    private func begin() {
        guard activity == nil else { return }
        activity = ProcessInfo.processInfo.beginActivity(options: [.idleSystemSleepDisabled, .suddenTerminationDisabled],
                                                         reason: "Updating Wizard OS")
    }
    private func end() {
        if let a = activity { ProcessInfo.processInfo.endActivity(a); activity = nil }
    }
}
