import AppKit
import Sparkle
import Darwin

/// The window is always dark (darkAqua), but a CGColor taken once from a dynamic NSColor resolves against the
/// Mac's own appearance. In Light Mode the bar was painted white behind the window's white text, so update and
/// upgrade messages were invisible. Resolve the colour whenever the bar draws, under its own appearance.
final class NoticeBarView: NSView {
    override var wantsUpdateLayer: Bool { true }
    override func updateLayer() { layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor }
}

/// Sparkle owns signature validation, download, atomic replacement and relaunch.
/// Wizard owns the top notice, explicit restart choice and local Host shutdown lease.
@MainActor final class WizardUpdater: NSObject, SPUUserDriver, SPUUpdaterDelegate {
    static let shared = WizardUpdater()
    let view = NoticeBarView()
    let label = NSTextField(wrappingLabelWithString: "")
    let action = NSButton(title: "Update and restart", target: nil, action: nil)
    let later = NSButton(title: "Later", target: nil, action: nil)
    var height: NSLayoutConstraint!
    private var updater: SPUUpdater!
    private var ready: ((SPUUserUpdateChoice) -> Void)?
    private var cancel: (() -> Void)?
    private var artifact: UpdateArtifact?
    private var verifiedArchive: (version: String, source: URL, relay: URL)?
    private var freshDownloadReady = false
    private var phaseHistory: [String] = []
    private var errorChain: [[String: Any]] = []
    private var quitDeadline: DispatchWorkItem?
    private var powerOffUntil = Date.distantPast
    private var powerOff: Bool { Date() < powerOffUntil }
    private var quitAfterStop = false
    private var powerOffObserver: NSObjectProtocol?
    private var cancellationSnapshot: URL { WizardUpdate.dir.appendingPathComponent("cancelled-release.json") }
    private var stagedSnapshot: URL { WizardUpdate.dir.appendingPathComponent("staged-release.json") }
    private var phase = "idle"
    private var message = ""
    private var version = ""
    private var expected: UInt64 = 0
    private var received: UInt64 = 0
    private var leaseFD: Int32 = -1
    private(set) var restartAuthorized = false
    private var preparing = false
    private var ordinaryQuitPending = false
    private var cancelledRelease: String?
    private var skipBeforeCancellation: [String: Any] = [:]
    private var installCycleActive = false
    var isRecording: () -> Bool = { false }
    // The main page owns manual mic/Right Command takes. Unknown activity
    // defers installation; the trusted page freezes new starts atomically.
    var admitWebRestart: (@escaping (Bool) -> Void) -> Void = { done in done(false) }
    var isPreparing: Bool { preparing || activatingGuest }
    /// Native recorder callbacks are synchronous. Read the live actor-owned
    /// gate only on the main thread; an unexpected background caller defers.
    nonisolated static var captureStartAllowed: Bool {
        guard Thread.isMainThread else { return false }
        return MainActor.assumeIsolated { !shared.isPreparing }
    }
    var onFreeze: (Bool) -> Void = { _ in }
    #if WIZARD_UPDATE_QA
    var qaBusy = false
    #else
    var qaBusy: Bool { false }
    #endif
    private var stoppedHost = false
    private var incomingGuest = false
    private var incomingReleaseID = ""
    private var plannedGuestActivation = false
    private(set) var activatingGuest = false
    var onGuestFinished: () -> Void = {}
    /// Upgrade progress and failure for the window's main overlay (text, failed). The window is frozen while the
    /// guest upgrades, so the overlay is the only large surface the owner sees.
    var onActivationStatus: (String, Bool) -> Void = { _, _ in }

    func attach(to root: NSView) -> NSView {
        view.translatesAutoresizingMaskIntoConstraints = false
        view.wantsLayer = true
        root.addSubview(view)
        height = view.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([view.leadingAnchor.constraint(equalTo: root.leadingAnchor), view.trailingAnchor.constraint(equalTo: root.trailingAnchor), view.topAnchor.constraint(equalTo: root.topAnchor), height])
        label.font = .systemFont(ofSize: 12); label.maximumNumberOfLines = 3
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        // The label takes the spare width; the buttons keep their natural size (Later used to stretch across the bar).
        label.setContentHuggingPriority(.defaultLow, for: .horizontal)
        for button in [action, later] {
            button.setContentHuggingPriority(.required, for: .horizontal)
            button.setContentCompressionResistancePriority(.required, for: .horizontal)
        }
        action.target = self; action.action = #selector(updateAndRestart)
        later.target = self; later.action = #selector(hideNotice)
        for control in [label, action, later] { control.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(control) }
        NSLayoutConstraint.activate([label.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 14), label.topAnchor.constraint(equalTo: view.topAnchor, constant: 30), label.trailingAnchor.constraint(equalTo: action.leadingAnchor, constant: -8), action.centerYAnchor.constraint(equalTo: label.centerYAnchor), action.trailingAnchor.constraint(equalTo: later.leadingAnchor, constant: -6), later.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -12), later.centerYAnchor.constraint(equalTo: label.centerYAnchor)])
        view.isHidden = true
        return view
    }
    func start() {
        do {
            let saved = WizardUpdate.json(cancellationSnapshot)
            cancelledRelease = saved["cancelledRelease"] as? String
            skipBeforeCancellation = saved["skipBeforeCancellation"] as? [String: Any] ?? [:]
            restoreCancelledRelease()
            try UpdateArtifact.sweepStaleDownloads()
            let discarded = FileManager.default.fileExists(atPath: stagedSnapshot.path)
            try? FileManager.default.removeItem(at: stagedSnapshot)
            powerOffObserver = NSWorkspace.shared.notificationCenter.addObserver(
                forName: NSWorkspace.willPowerOffNotification, object: nil, queue: .main
            ) { [weak self] _ in
                MainActor.assumeIsolated { self?.requestPowerOff() }
            }
            try WizardRelease.read(Bundle.main.bundleURL).validate(Bundle.main.bundleURL, verifyGuestFiles: false)
            updater = SPUUpdater(hostBundle: .main, applicationBundle: .main, userDriver: self, delegate: self)
            try updater.start()
            // Every archive must traverse our checksum/user-driver path. Never
            // let Sparkle's silent-download driver stage an unchecked archive.
            updater.automaticallyDownloadsUpdates = false
            if discarded {
                show("discarded", "Previously staged update discarded — Check for updates again to verify a fresh download", retry: true)
            } else if updater.automaticallyChecksForUpdates { updater.checkForUpdatesInBackground() }
            recoverActivation()
        } catch { show("failed", "Updates unavailable — \(error.localizedDescription)", retry: true) }
    }
    /// Called before *every* local boot, including switching from a remote backend.
    /// No missing HTTP route is interpreted as idle. A running legacy Host defers.
    func admitLegacyBootstrap() -> Bool {
        guard Store.active?.kind == .thisMac, WizardShared.legacyBootstrapNeeded else { return false }
        guard !activatingGuest else { return true }
        if HostControl.isRunning || HostControl.hasForeignRunner || isRecording() || qaBusy {
            show("busy", "Quit the old Wizard Host and finish capture before upgrading this local disk.")
            return true
        }
        let alert = NSAlert()
        alert.messageText = "Upgrade this Mac’s existing Wizard?"
        alert.informativeText = "Your accounts, chats, files and installed apps stay on the existing disk. Wizard will first make a stopped-disk rollback copy, then upgrade in a restricted maintenance boot. The old agents will not start during the upgrade."
        alert.addButton(withTitle: "Upgrade existing Wizard")
        alert.addButton(withTitle: "Not now")
        guard alert.runModal() == .alertFirstButtonReturn else {
            show("deferred", "Local Wizard remains stopped. Choose This Mac again when ready to upgrade.")
            return true
        }
        let ownership = WizardDiskOwnership()
        do {
            guard !HostControl.isRunning, !HostControl.hasForeignRunner, !isRecording(), !qaBusy else {
                throw WizardUpdate.error("Activity changed while confirming; upgrade deferred")
            }
            try ownership.acquire()
            let pins = ["boot/vmlinux": "5028c424ee9fd0f4d18c38269122e30e3d084deb1b13404ab070a3f478ddd30a",
                        "boot/initrd": "b32a28fd79ea7cedea49520befe694f513fb35af53203074006a016128c3c06b"]
            for (path, digest) in pins {
                guard try WizardUpdate.sha256(WizardShared.osDir.appendingPathComponent(path)) == digest else {
                    throw WizardUpdate.error("Unknown legacy boot files; disk left untouched")
                }
            }
            let release = try WizardRelease.read(Bundle.main.bundleURL)
            try release.validate(Bundle.main.bundleURL)
            guard release.guestPatch == "mac-stack-v1",
                  FileManager.default.fileExists(atPath: Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/GuestUpdate/source/next/guest/cold-bootstrap.py").path) else {
                throw WizardUpdate.error("This app does not contain the authenticated cold bootstrap")
            }
            try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            leaseFD = open(WizardUpdate.dir.appendingPathComponent("lease").path, O_CREAT | O_RDWR, 0o600)
            guard leaseFD >= 0, flock(leaseFD, LOCK_EX | LOCK_NB) == 0 else { throw WizardUpdate.error("Another upgrade owns this disk") }
            guard !HostControl.isRunning, !HostControl.hasForeignRunner, !isRecording() else { throw WizardUpdate.error("Activity changed during validation; disk untouched") }
            preparing = true; activatingGuest = true; onFreeze(true)
            try WizardGuestActivation.snapshotStoppedDisk()
            let nonce = UUID().uuidString
            try WizardUpdate.write(["kind": "legacy-cold", "phase": "installing", "nonce": nonce,
                "diskIdentity": WizardShared.diskIdentity, "dataHome": WizardShared.supportDir.path,
                "appPath": Bundle.main.bundleURL.path, "releaseID": release.releaseID,
                "from": "0.6.1", "to": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") ?? "",
                "guestPatch": true, "applyGuest": true], WizardUpdate.journal)
            try WizardUpdate.write(["token": nonce, "admission": "cold-pid1"], WizardUpdate.maintenanceJournal)
            ownership.release()
            WizardGuestActivation.shared.onProgress = { [weak self] text in
                self?.show("guest-activating", text); self?.onActivationStatus(text, false)
            }
            WizardGuestActivation.shared.onDone = { [weak self] error in
                guard let self else { return }
                self.activatingGuest = false; self.releaseLease()
                if let error { self.onActivationStatus(error, true) }
                if error == nil {
                    // Disk-bound normal-boot receipt was persisted under ownership
                    // before launching the Host; this callback confirms live health.
                    self.onGuestFinished()
                }
                self.show(error == nil ? "installed" : "failed", error ?? "Existing Wizard upgraded; your data is preserved.")
            }
            WizardGuestActivation.shared.activate()
        } catch {
            ownership.release(); activatingGuest = false; releaseLease()
            show("failed", "Legacy upgrade deferred — \(error.localizedDescription)")
        }
        return true
    }
    @objc func checkForUpdates(_ sender: Any? = nil) {
        guard let updater else { return }
        if ready != nil { show("ready", "Update \(version) available — ready to restart"); return }
        if updater.canCheckForUpdates { updater.checkForUpdates() }
    }
    @objc private func hideNotice() { view.isHidden = true; height.constant = 0 }
    private var noticeToken = UUID()
    private func show(_ state: String, _ text: String, retry: Bool = false) {
        let state = restartAuthorized && ["downloading", "verifying"].contains(state) ? "installing" : state
        let text = restartAuthorized && state == "installing" ? "Installing update and restarting…" : text
        phase = state; message = text; label.stringValue = text
        if phaseHistory.last != state { phaseHistory.append(state); phaseHistory = Array(phaseHistory.suffix(64)) }
        view.isHidden = false; height?.constant = 94
        action.title = retry ? "Retry" : "Update and restart"
        action.isEnabled = retry || ready != nil && !preparing
        // Offer the button only when it can do something (a ready update or a retry), not greyed out under news.
        action.isHidden = !(retry || ready != nil)
        later.isEnabled = !preparing
        try? WizardUpdate.write(snapshot, WizardUpdate.dir.appendingPathComponent("ui.json"))
        // Good news needs no answer: let it go by itself unless something newer replaced it.
        let token = UUID(); noticeToken = token
        if state == "installed" || state == "current" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
                guard let self, self.noticeToken == token, !self.preparing else { return }
                self.hideNotice()
            }
        }
    }
    var snapshot: [String: Any] {
        let installed = NSDictionary(contentsOf: Bundle.main.bundleURL.appendingPathComponent("Contents/Info.plist"))?["CFBundleVersion"] as? String ?? "unconfirmed"
        return ["phaseHistory": phaseHistory, "errors": errorChain, "freshDownloadReady": freshDownloadReady, "pid": getpid(), "appPath": Bundle.main.bundleURL.path, "phase": phase, "message": message, "version": version, "build": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") ?? "", "installedBundleBuild": installed, "ready": ready != nil, "restartAuthorized": restartAuthorized, "preparing": preparing, "dataHome": WizardShared.supportDir.path, "hostRunning": HostControl.isRunning, "recording": isRecording(), "visible": !view.isHidden]
    }
    private func requestPowerOff() {
        powerOffUntil = Date().addingTimeInterval(3)
        guard !activatingGuest, !restartAuthorized else { return }
        artifact?.cancel()
        // Production never creates a Sparkle installer before explicit restart
        // admission. A pre-installer reply only cancels the download cycle.
        if let reply = ready { ready = nil; discardStagedUpdate(reply) }
        else if let cancel { self.cancel = nil; cancel() }
        releaseLease()
    }
    private func deferQuit() {
        ordinaryQuitPending = true
        show("quit-deferring", "Finishing update preparation before quitting… (up to 45 seconds)")
        guard quitDeadline == nil else { return }
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.quitDeadline = nil
            guard self.ordinaryQuitPending else { return }
            self.show("quit-timeout", "Update preparation stopped — quitting Wizard")
            self.ordinaryQuitPending = false
            self.installCycleActive = false
            self.artifact?.cancel()
            self.releaseLease()
            NSApp.terminate(nil)
        }
        quitDeadline = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 45, execute: work)
    }
    func shouldTerminate() -> NSApplication.TerminateReply {
        if restartAuthorized { return .terminateNow }
        if powerOff { requestPowerOff(); return .terminateNow }
        if activatingGuest { return .terminateCancel }
        if preparing {
            quitAfterStop = true
            show("stopping", "Finishing safe Host shutdown before quitting… (up to 105 seconds)")
            return .terminateCancel
        }
        if let reply = ready {
            deferQuit(); ready = nil; discardStagedUpdate(reply); return .terminateCancel
        }
        if let cancel {
            deferQuit(); self.cancel = nil; cancel(); return .terminateCancel
        }
        if preparing { releaseLease() }
        if installCycleActive { deferQuit(); return .terminateCancel }
        return .terminateNow
    }
    @objc func updateAndRestart() {
        if ready == nil { checkForUpdates(); return }
        guard !preparing else { return }
        if isRecording() || qaBusy { show("busy", "Recording or agent work is active — update after it finishes"); return }
        if HostControl.hasForeignRunner { show("busy", "Another candidate's Wizard Host is running — close that candidate before updating"); return }
        plannedGuestActivation = incomingGuest && Store.active?.kind == .thisMac && WizardShared.osInstalled
        stoppedHost = false; quitAfterStop = false
        preparing = true
        admitWebRestart { [weak self] idle in
            guard let self, self.preparing else { return }
            guard idle, !self.isRecording(), !self.qaBusy else {
                self.preparing = false; self.onFreeze(false)
                self.show("busy", "Finish recording or let the chat finish loading before updating")
                return
            }
            if self.quitAfterStop { self.fail("Restart cancelled by Quit"); return }
            self.onFreeze(true)
            self.prepareIdleHost()
        }
    }
    private func prepareIdleHost() {
        WizardUpdate.idle { [weak self] reason in
            guard let self else { return }
            guard self.preparing, self.ready != nil, !self.ordinaryQuitPending, !self.powerOff else { self.fail("Restart preparation cancelled"); return }
            if self.quitAfterStop { self.fail("Restart cancelled by Quit"); return }
            if let reason { self.preparing = false; self.onFreeze(false); self.show("busy", reason); return }
            do {
                try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                self.leaseFD = open(WizardUpdate.dir.appendingPathComponent("lease").path, O_CREAT | O_RDWR, 0o600)
                guard self.leaseFD >= 0, flock(self.leaseFD, LOCK_EX | LOCK_NB) == 0 else { throw WizardUpdate.error("Another update is already active") }
                try self.artifact?.requireLive()
                guard self.artifact != nil else { throw WizardUpdate.error("Verified archive is unavailable") }
                try self.artifact?.requireAdmissionCapacity(Bundle.main.bundleURL)
                let prior = WizardUpdate.dir.appendingPathComponent("previous.app")
                try? FileManager.default.removeItem(at: prior)
                try WizardUpdate.run("/usr/bin/ditto", [Bundle.main.bundleURL.path, prior.path])
                let nonce = UUID().uuidString
                self.stoppedHost = HostControl.isRunning
                try WizardUpdate.write(["nonce": nonce, "pid": getpid(), "peer": WizardRelease.peer, "expires": Date().timeIntervalSince1970 + 110, "appPath": Bundle.main.bundleURL.standardizedFileURL.path], WizardUpdate.request)
                try WizardUpdate.write(["nonce": nonce, "from": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") ?? "", "to": self.version, "releaseID": self.incomingReleaseID, "guestPatch": self.incomingGuest, "applyGuest": self.plannedGuestActivation, "phase": "prepared", "appPath": Bundle.main.bundleURL.path, "restartHost": self.stoppedHost, "dataHome": WizardShared.supportDir.path, "previous": prior.path], WizardUpdate.journal)
                if !self.stoppedHost {
                    if self.quitAfterStop { self.fail("Restart cancelled by Quit") } else { self.install() }; return
                }
                guard WizardUpdate.json(WizardShared.statusFile)["hostProtocol"] as? Int == WizardRelease.peer else { throw WizardUpdate.error("Installed Host needs the updater bootstrap first") }
                HostControl.send("prepare-update")
                self.show("stopping", "Stopping local Wizard OS safely before restarting…")
                self.waitForHost(nonce: nonce, deadline: Date().addingTimeInterval(105))
            } catch { self.fail(error.localizedDescription) }
        }
    }
    private func waitForHost(nonce: String, deadline: Date) {
        guard preparing, ready != nil, !ordinaryQuitPending, !powerOff else { fail("Restart preparation cancelled"); return }
        let response = WizardUpdate.json(WizardUpdate.response)
        if response["nonce"] as? String == nonce {
            let state = response["state"] as? String
            if state == "failed" || state == "busy" { fail(response["error"] as? String ?? "Host could not stop safely"); return }
            if state == "stopped", !HostControl.isRunning {
                if quitAfterStop { fail("Restart cancelled by Quit") } else { install() }; return
            }
        }
        guard Date() < deadline else { fail("Host shutdown was not confirmed — prior app remains installed"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.waitForHost(nonce: nonce, deadline: deadline) }
    }
    private func install() {
        guard !isRecording(), !qaBusy, ready != nil else { fail("Activity started; restart deferred"); return }
        admitWebRestart { [weak self] idle in
            guard let self, self.preparing else { return }
            guard idle, !self.isRecording(), !self.qaBusy else { self.fail("Recording started or its state is unknown; restart deferred"); return }
            self.installApproved()
        }
    }
    private func installApproved() {
        guard !ordinaryQuitPending, !powerOff, !isRecording(), !qaBusy, let reply = ready else { fail("Activity started; restart deferred"); return }
        do {
            if plannedGuestActivation { try WizardGuestActivation.snapshotStoppedDisk() }
        } catch { fail(error.localizedDescription); return }
        try? FileManager.default.removeItem(at: stagedSnapshot)
        restartAuthorized = true; ready = nil; cancel = nil; freshDownloadReady = false
        var journal = WizardUpdate.json(WizardUpdate.journal); journal["phase"] = "installing"
        do { try WizardUpdate.write(journal, WizardUpdate.journal) } catch { restartAuthorized = false; ready = reply; fail(error.localizedDescription); return }
        show("installing", "Installing update and restarting…")
        reply(.install)
    }
    private func releaseLease() {
        try? FileManager.default.removeItem(at: WizardUpdate.request)
        if leaseFD >= 0 { flock(leaseFD, LOCK_UN); close(leaseFD); leaseFD = -1 }
        preparing = false; onFreeze(false)
    }
    private func fail(_ text: String) {
        restartAuthorized = false; releaseLease()
        var journal = WizardUpdate.json(WizardUpdate.journal)
        if journal["phase"] as? String == "prepared" || journal["phase"] as? String == "installing" { journal["phase"] = "install-failed"; try? WizardUpdate.write(journal, WizardUpdate.journal) }
        if stoppedHost && !HostControl.isRunning { HostControl.ensureRunning() }
        show("failed", "Update failed — \(text). Previous installed app or retained recovery bundle remains available.", retry: ready == nil)
        if quitAfterStop {
            quitAfterStop = false
            finishRollbackQuit(deadline: Date().addingTimeInterval(15))
        }
    }
    private func finishRollbackQuit(deadline: Date) {
        if !stoppedHost || HostControl.isRunning { NSApp.terminate(nil); return }
        guard Date() < deadline else { show("failed", "Host restart was not confirmed — Quit cancelled"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.finishRollbackQuit(deadline: deadline) }
    }
    private func recoverActivation() {
        var journal = WizardUpdate.json(WizardUpdate.journal)
        guard journal["dataHome"] as? String == WizardShared.supportDir.path else { return }
        if journal["phase"] as? String == "guest-activating" {
            activatingGuest = true; preparing = true; onFreeze(true)
            WizardGuestActivation.shared.onProgress = { [weak self] text in
                self?.show("recovering", text); self?.onActivationStatus(text, false)
            }
            WizardGuestActivation.shared.onDone = { [weak self] error in
                guard let self else { return }
                self.activatingGuest = false; self.releaseLease(); self.onGuestFinished()
                self.show("failed", error ?? "Interrupted update recovered; prior guest restored")
            }
            WizardGuestActivation.shared.recoverInterruptedActivation()
            return
        }
        guard journal["phase"] as? String == "installing" else {
            if ["prepared", "install-failed", "guest-activated", "guest-rolled-back"].contains(journal["phase"] as? String ?? "") { releaseLease() }
            return
        }
        let current = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""
        guard current != journal["from"] as? String else { releaseLease(); show("failed", "Previous app preserved — installation did not complete", retry: true); return }
        do {
            let release = try WizardRelease.read(Bundle.main.bundleURL); try release.validate(Bundle.main.bundleURL)
            guard current == journal["to"] as? String, release.releaseID == journal["releaseID"] as? String,
                  (release.guestPatch != nil) == journal["guestPatch"] as? Bool else { throw WizardUpdate.error("Installed release does not match the approved transaction") }
            if release.guestPatch != nil, journal["applyGuest"] as? Bool == true {
                activatingGuest = true; preparing = true; onFreeze(true)
                WizardGuestActivation.shared.onProgress = { [weak self] text in self?.show("guest-activating", text) }
                WizardGuestActivation.shared.onDone = { [weak self] error in
                    guard let self else { return }
                    self.activatingGuest = false; self.releaseLease(); self.onGuestFinished()
                    self.show(error == nil ? "installed" : "failed", error ?? "Wizard and local software updated — build \(current)")
                }
                WizardGuestActivation.shared.activate()
                return
            }
            releaseLease()
            if journal["restartHost"] as? Bool == true {
                HostControl.ensureRunning()
                show("activating", "Mac app installed; confirming new local Host…")
                confirmNativeHost(build: current, deadline: Date().addingTimeInterval(300))
            } else {
                journal["phase"] = "native-activated"; journal["installedBuild"] = current
                try WizardUpdate.write(journal, WizardUpdate.journal)
                show("installed", "Wizard updated — build \(current)")
            }
        } catch { releaseLease(); show("failed", "New app health failed — previous app retained in updates/previous.app", retry: false) }
    }

    private func confirmNativeHost(build: String, deadline: Date) {
        let status = WizardUpdate.json(WizardShared.statusFile)
        if status["build"] as? String == build, status["hostProtocol"] as? Int == WizardRelease.peer,
           status["dataHome"] as? String == WizardShared.supportDir.path,
           let pid = status["pid"] as? Int32, kill(pid, 0) == 0 {
            if status["state"] as? String == "notInstalled" { nativeActivated(build); return }
            if status["state"] as? String == "running" {
                WizardShared.probeReady { ready in DispatchQueue.main.async {
                    if ready { self.nativeActivated(build) }
                    else { self.retryNativeHost(build, deadline) }
                } }
                return
            }
        }
        retryNativeHost(build, deadline)
    }
    private func retryNativeHost(_ build: String, _ deadline: Date) {
        guard Date() < deadline else { show("failed", "New Host health not confirmed — previous app remains available in updates/previous.app"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.confirmNativeHost(build: build, deadline: deadline) }
    }
    private func nativeActivated(_ build: String) {
        var journal = WizardUpdate.json(WizardUpdate.journal); journal["phase"] = "native-activated"; journal["installedBuild"] = build; journal["hostBuild"] = build
        do { try WizardUpdate.write(journal, WizardUpdate.journal); show("installed", "Wizard and local Host updated — build \(build)") }
        catch { show("failed", "Installed Host verified; activation receipt could not be saved") }
    }
    func updater(_ updater: SPUUpdater, shouldProceedWithUpdate item: SUAppcastItem, updateCheck: SPUUpdateCheck) throws {
        artifact?.cancel(); artifact = nil; verifiedArchive = nil
        guard !item.isDeltaUpdate, item.deltaUpdates?.isEmpty != false else {
            throw WizardUpdate.error("Delta updates are not supported — full archive required")
        }
        errorChain = []
        let properties = item.propertiesDictionary
        guard let hash = properties["wizard:sha256"] as? String,
              hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              let url = item.fileURL, UpdateArtifact.allowed(url), item.contentLength > 0 else {
            throw WizardUpdate.error("Update feed is missing archive SHA-256, size or a secure URL")
        }
        guard let text = properties["wizard:contract"] as? String, let data = text.data(using: .utf8),
              let contract = try? JSONDecoder().decode(WizardRelease.self, from: data),
              contract.schema == 1, contract.arch == "arm64", contract.minimumPeer <= WizardRelease.peer,
              contract.hostProtocol == WizardRelease.peer, contract.build == item.versionString,
              !contract.releaseID.isEmpty, item.installationType == "application" else { throw WizardUpdate.error("Incompatible release contract — prior app preserved") }
        try contract.validateMetadata()
        incomingGuest = contract.guestPatch != nil
        incomingReleaseID = contract.releaseID
    }
    func updater(_ updater: SPUUpdater, willDownloadUpdate item: SUAppcastItem, with request: NSMutableURLRequest) {
        // A new cycle must never fall back to an unverified network download.
        if let verifiedArchive, verifiedArchive.version == item.versionString,
           verifiedArchive.source == item.fileURL, !item.isDeltaUpdate {
            request.url = verifiedArchive.relay
        } else { request.url = URL(string: "wizard-unverified-update-refused:archive")! }
    }
    func updater(_ updater: SPUUpdater, didDownloadUpdate item: SUAppcastItem) {
        artifact?.cancel(); artifact = nil; verifiedArchive = nil
    }
    func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        artifact?.cancel(); artifact = nil; verifiedArchive = nil
        captureError(error)
        if restartAuthorized || preparing { fail(error.localizedDescription); return }
        if (error as NSError).code != 1001 { show("failed", "Update access unavailable or validation failed — \(error.localizedDescription)", retry: true) }
    }
    private func captureError(_ error: Error) {
        errorChain = []
        var current: NSError? = error as NSError
        while let value = current, errorChain.count < 12 {
            errorChain.append(["domain": value.domain, "code": value.code])
            current = value.userInfo[NSUnderlyingErrorKey] as? NSError
        }
    }
    func show(_ request: SPUUpdatePermissionRequest, reply: @escaping (SUUpdatePermissionResponse) -> Void) { reply(SUUpdatePermissionResponse(automaticUpdateChecks: true, sendSystemProfile: false)) }
    func showUserInitiatedUpdateCheck(cancellation: @escaping () -> Void) { cancel = cancellation; show("checking", "Checking for updates…") }
    func showUpdateFound(with item: SUAppcastItem, state: SPUUserUpdateState, reply: @escaping (SPUUserUpdateChoice) -> Void) {
        version = item.versionString; installCycleActive = true
        guard state.stage == .notDownloaded else {
            // Sparkle may restore a download/installer from a previous process.
            // Its bytes were not verified by this session, and .install here can
            // skip showReady entirely. Purge it, never authorize restart here.
            show("discarded", "Previously staged update discarded — Check for updates again to verify a fresh download", retry: true)
            discardStagedUpdate(reply); return
        }
        if item.isInformationOnlyUpdate { show("unavailable", "Update available but cannot be downloaded from this feed"); reply(.dismiss); return }
        show("available", "Update \(item.displayVersionString) available — downloading…")
        // Keep the authenticated item unchanged. Only Sparkle's download request is
        // redirected to the verified bytes; its Ed25519 and bundle checks still run.
        let download = UpdateArtifact(); artifact = download
        download.onInvalidated = { [weak self, weak download] error in
            guard let self, self.artifact === download else { return }
            let reply = self.ready; self.ready = nil; self.verifiedArchive = nil
            self.fail(error.localizedDescription); reply?(.dismiss)
        }
        cancel = { [weak self] in
            download.cancel(); self?.artifact = nil; self?.verifiedArchive = nil; reply(.dismiss)
        }
        do {
            guard let url = item.fileURL, let hash = item.propertiesDictionary["wizard:sha256"] as? String else {
                throw WizardUpdate.error("Missing archive digest")
            }
            let enclosure = item.propertiesDictionary["enclosure"] as? [String: Any]
            guard let signature = enclosure?["sparkle:edSignature"] as? String,
                  let publicKey = Bundle.main.object(forInfoDictionaryKey: "SUPublicEDKey") as? String else {
                throw WizardUpdate.error("Missing archive Ed25519 signature or public key")
            }
            download.signature = signature; download.publicKey = publicKey
            #if WIZARD_UPDATE_QA
            download.skipPrivateSignature = UserDefaults.standard.bool(forKey: "QAHooks") && UserDefaults.standard.bool(forKey: "QAUpdateSkipPrivateSignature")
            #endif
            try download.fetch(url, hash: hash, bytes: item.contentLength, progress: { [weak self] received, expected in
                guard let self, self.artifact === download else { return }
                self.show("downloading", "Update available — downloading \(min(100, Int(Double(received) / Double(expected) * 100)))%")
            }, completion: { [weak self] result in
                guard let self, self.artifact === download else { return }
                self.cancel = nil
                switch result {
                case .success(let url):
                    self.verifiedArchive = (item.versionString, item.fileURL!, url)
                    do {
                        try WizardUpdate.write(["version": item.versionString], self.stagedSnapshot)
                        // Ready means privately downloaded, not Sparkle stage 1.
                        // Sparkle 2.10 installs stage 1 on host death; start it only
                        // after the same explicit restart/Host admission as install.
                        self.freshDownloadReady = true; self.ready = reply
                        self.show("ready", "Update \(self.version) available — ready to restart")
                        #if WIZARD_UPDATE_QA
                        let defaults = UserDefaults.standard
                        if defaults.bool(forKey: "QAHooks") && defaults.bool(forKey: "QAQuitDuringUpdateExtraction") {
                            self.ready = nil; self.freshDownloadReady = false
                            reply(.install)
                        }
                        #endif
                    } catch {
                        download.cancel(); self.artifact = nil
                        self.show("failed", error.localizedDescription, retry: true); reply(.dismiss)
                    }
                case .failure(let error): self.artifact = nil; self.show("failed", error.localizedDescription, retry: true); reply(.dismiss)
                }
            })
        } catch { artifact = nil; cancel = nil; download.cancel(); show("failed", error.localizedDescription, retry: true); reply(.dismiss) }
    }
    func showUpdateReleaseNotes(with downloadData: SPUDownloadData) {}
    func showUpdateReleaseNotesFailedToDownloadWithError(_ error: Error) {}
    func showUpdateNotFoundWithError(_ error: Error, acknowledgement: @escaping () -> Void) { cancel = nil; show("current", "No compatible newer update is available", retry: true); acknowledgement() }
    func showUpdaterError(_ error: Error, acknowledgement: @escaping () -> Void) { captureError(error); cancel = nil; ready = nil; fail(error.localizedDescription); acknowledgement() }
    func showDownloadInitiated(cancellation: @escaping () -> Void) { cancel = cancellation; expected = 0; received = 0; show("downloading", "Update available — downloading…") }
    func showDownloadDidReceiveExpectedContentLength(_ expectedContentLength: UInt64) { expected = expectedContentLength }
    func showDownloadDidReceiveData(ofLength length: UInt64) { received += length; show("downloading", expected > 0 ? "Update available — downloading \(min(100, Int(Double(received) / Double(expected) * 100)))%" : "Update available — downloading…") }
    func showDownloadDidStartExtractingUpdate() {
        cancel = nil; show("verifying", "Verifying complete App + Host update…")
        #if WIZARD_UPDATE_QA
        let defaults = UserDefaults.standard
        if defaults.bool(forKey: "QAHooks") && defaults.bool(forKey: "QAQuitDuringUpdateExtraction") {
            defaults.removeObject(forKey: "QAQuitDuringUpdateExtraction")
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
        #endif
    }
    func showExtractionReceivedProgress(_ progress: Double) { if !ordinaryQuitPending { show("verifying", "Preparing update \(Int(progress * 100))%") } }
    func showReady(toInstallAndRelaunch reply: @escaping (SPUUserUpdateChoice) -> Void) {
        cancel = nil; freshDownloadReady = false
        try? FileManager.default.removeItem(at: stagedSnapshot)
        if ordinaryQuitPending { discardStagedUpdate(reply); return }
        if restartAuthorized { reply(.install); return }
        show("discarded", "Unadmitted Sparkle stage discarded — Check for updates again", retry: true)
        discardStagedUpdate(reply)
    }
    func showInstallingUpdate(withApplicationTerminated applicationTerminated: Bool, retryTerminatingApplication: @escaping () -> Void) {
        show("installing", "Installing update and restarting…")
        // Installation handoff is confirmed. Quit ourselves after the deliberate
        // restart lease, rather than depending on a helper's cross-app quit event.
        if restartAuthorized && !applicationTerminated { DispatchQueue.main.async { NSApp.terminate(nil) } }
    }
    func showUpdateInstalledAndRelaunched(_ relaunched: Bool, acknowledgement: @escaping () -> Void) { acknowledgement() }
    private func discardStagedUpdate(_ reply: (SPUUserUpdateChoice) -> Void) {
        if freshDownloadReady {
            freshDownloadReady = false
            try? FileManager.default.removeItem(at: stagedSnapshot)
            reply(.dismiss); return
        }
        // Sparkle 2.10 requires Skip, not Dismiss, to tear down an installing
        // update. This is cancellation, never the user's "skip this release".
        cancelledRelease = version
        let defaults = UserDefaults.standard
        skipBeforeCancellation = [:]
        for key in ["SUSkippedVersion", "SUSkippedMajorVersion", "SUSkippedMajorSubreleaseVersion"] {
            if let value = defaults.object(forKey: key) { skipBeforeCancellation[key] = value }
        }
        do {
            try WizardUpdate.write(["cancelledRelease": version, "skipBeforeCancellation": skipBeforeCancellation], cancellationSnapshot)
        } catch {
            show("failed", "Cannot persist update cancellation — \(error.localizedDescription)")
        }
        reply(.skip)
    }
    private func restoreCancelledRelease() {
        guard let cancelledRelease else { return }
        let defaults = UserDefaults.standard
        // Pinned Sparkle 2.10's internal source keys (SPUSkippedUpdate.m /
        // SUConstants.m). Clear only our cancellation, never another skip.
        func restore(_ key: String) {
            if let previous = skipBeforeCancellation[key] { defaults.set(previous, forKey: key) }
            else { defaults.removeObject(forKey: key) }
        }
        if defaults.string(forKey: "SUSkippedVersion") == cancelledRelease { restore("SUSkippedVersion") }
        if defaults.string(forKey: "SUSkippedMajorSubreleaseVersion") == cancelledRelease {
            restore("SUSkippedMajorVersion"); restore("SUSkippedMajorSubreleaseVersion")
        }
        defaults.synchronize()
        try? FileManager.default.removeItem(at: cancellationSnapshot)
        self.cancelledRelease = nil; skipBeforeCancellation = [:]
    }
    func dismissUpdateInstallation() {
        #if WIZARD_UPDATE_QA
        // Simulate a missing final acknowledgement without stalling the main
        // event loop or creating an unadmitted Sparkle installer.
        let defaults = UserDefaults.standard
        if ordinaryQuitPending && freshDownloadReady == false && defaults.bool(forKey: "QAStallUpdateDismiss") {
            defaults.removeObject(forKey: "QAStallUpdateDismiss")
            artifact?.cancel(); artifact = nil; verifiedArchive = nil
            cancel = nil; ready = nil
            return
        }
        #endif
        restoreCancelledRelease(); installCycleActive = false
        quitDeadline?.cancel(); quitDeadline = nil
        if ordinaryQuitPending { show("quit-dismissed", "Update preparation dismissed — quitting Wizard") }
        artifact?.cancel(); artifact = nil; verifiedArchive = nil
        cancel = nil; ready = nil
        if !restartAuthorized { releaseLease() }
        if ordinaryQuitPending { ordinaryQuitPending = false; DispatchQueue.main.async { NSApp.terminate(nil) } }
    }
}
