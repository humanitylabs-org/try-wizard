import Foundation
#if os(Linux)
import Glibc
/// APFS clonefile stand-in for the Linux run: a plain copy (the rig only checks which disk ends up live).
func clonefile(_ src: String, _ dst: String, _ flags: UInt32) -> Int32 {
    (try? FileManager.default.copyItem(atPath: src, toPath: dst)) != nil ? 0 : -1
}
#endif

// try-wizard#191 (kicked back on 0.8.18): runs the production WizardGuestActivation.swift (the App's activation state
// machine, unchanged) against a scripted Host. Only the Host and its VM are played; every App-side decision is the
// shipped code. The mode picks how the Host answers the stop that ends the maintenance boot after the guest applied
// the update (prepare-update with maintenance: true):
//   ok           the guest stops cleanly at once
//   slow         the clean stop outlasts the Host's budget: the Host answers failed "Clean shutdown timed out" (as
//                VM.stop(forceOnTimeout: false) does) and the guest finishes powering off later
//   busy         the lease ask for that stop is refused twice (state busy), then granted
//   full-slow    as slow, but the receipt is not a code-only one: the update must not be recorded as activated
//   failed-slow  the guest refused the update itself, then the stop is slow: nothing may be recorded as activated
// After the activation ends the rig plays what the window does next (onGuestFinished -> begin -> connectLocal:
// ensureRunning + "start", and once more a moment later) and reports what the guest ends up running. It checks the
// final phase, the receipt's disk binding, the lease and the kind of boot, never only that a receipt exists.
enum WizardShared {
    static let supportDir = URL(fileURLWithPath: CommandLine.arguments[1])
    static var logsDir: URL { supportDir }
    static var osDir: URL { supportDir.appendingPathComponent("os") }
    static var statusFile: URL { supportDir.appendingPathComponent("host-status.json") }
    static let osInstalled = true
    static var coldBootstrapToken: String? { nil }
    /// Shared.swift: the bundled payload is attached, so the boot is a maintenance boot, while the journal says
    /// guest-activating.
    static var guestUpdatePayload: URL? {
        WizardUpdate.json(WizardUpdate.journal)["phase"] as? String == "guest-activating" ? supportDir : nil
    }
}
enum WizardRelease { static let peer = 1 }
enum WizardUpdate {
    static var dir: URL { WizardShared.supportDir.appendingPathComponent("updates") }
    static var journal: URL { dir.appendingPathComponent("journal.json") }
    static var request: URL { dir.appendingPathComponent("request.json") }
    static var response: URL { dir.appendingPathComponent("response.json") }
    static var maintenanceJournal: URL { dir.appendingPathComponent("maintenance-lease.json") }
    static func json(_ url: URL) -> [String: Any] { (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any] ?? [:] }
    static func write(_ value: [String: Any], _ url: URL) throws { try JSONSerialization.data(withJSONObject: value).write(to: url, options: .atomic) }
    static func error(_ text: String) -> NSError { NSError(domain: "activation-stop", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
    static func idle(_ done: @escaping (String?) -> Void) { done(FileManager.default.fileExists(atPath: maintenanceJournal.path) ? "held" : nil) }
}

let mode = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "ok"
let t0 = Date()
func say(_ s: String) { print(String(format: "%6.1f s  ", Date().timeIntervalSince(t0)) + s); fflush(stdout) }

/// The guest as the Host sees it: off, a maintenance boot (lease held, launch admission closed), an ordinary boot,
/// or powering off.
enum Guest: String { case off, maintenance, normal, stopping }
@MainActor enum HostControl {
    static var isRunning = false
    static var hasForeignRunner = false
    static var guest = Guest.off
    static var busyLeft = 2
    static func status(_ s: String) { try! WizardUpdate.write(["state": s, "updatedAt": Date().timeIntervalSince1970], WizardShared.statusFile) }
    static func boot() {
        guest = WizardShared.guestUpdatePayload != nil ? .maintenance : .normal
        status("running")
        say("guest booted: \(guest.rawValue)")
    }
    /// Host main.swift: every 3 s, a running VM with no payload attached gives the lease back (played every 0.3 s).
    static func releaseLoop() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            if isRunning, guest == .normal || guest == .maintenance, WizardShared.guestUpdatePayload == nil,
               FileManager.default.fileExists(atPath: WizardUpdate.maintenanceJournal.path) {
                try? FileManager.default.removeItem(at: WizardUpdate.maintenanceJournal)
                say("Host gave the maintenance lease back (launch admission open)")
            }
            releaseLoop()
        }
    }
    static func ensureRunning() { if !isRunning { isRunning = true; say("Host launched"); boot() } }
    static func waitForLocalWizard(timeout: TimeInterval, tick: @escaping (TimeInterval) -> Void, done: @escaping (Bool) -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { done(isRunning && (guest == .normal || guest == .maintenance)) }
    }
    static func send(_ command: String) {
        say("App -> Host: \(command)")
        switch command {
        case "apply-guest-update":
            let nonce = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-command.json"))["nonce"]!
            // Host applyGuestUpdate: the lease (journal token) is granted, then code-update.py runs in the guest.
            try! WizardUpdate.write(["token": WizardUpdate.json(WizardUpdate.journal)["nonce"]!], WizardUpdate.maintenanceJournal)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                if mode == "failed-slow" {
                    try! WizardUpdate.write(["nonce": nonce, "state": "failed", "error": "Guest migration failed; private updater.log retained"],
                                            WizardUpdate.dir.appendingPathComponent("guest-response.json"))
                    say("guest refused the update"); return
                }
                try! Data("APPLIED".utf8).write(to: WizardShared.osDir.appendingPathComponent("disk.img"))
                var receipt: [String: Any] = ["patch": "mac-stack-v1", "service_image": "sha256:test", "permanent_identity_credentials_preserved": true]
                if mode != "full-slow" { receipt["kind"] = "code-only" }
                try! WizardUpdate.write(["nonce": nonce, "state": "applied", "receipt": receipt], WizardUpdate.dir.appendingPathComponent("guest-response.json"))
                say("guest applied the update (WIZARD_PATCH_OK receipt)")
            }
        case "prepare-update":
            let nonce = WizardUpdate.json(WizardUpdate.request)["nonce"]!
            if mode == "busy" && busyLeft > 0 {
                busyLeft -= 1
                try! WizardUpdate.write(["nonce": nonce, "state": "busy", "error": "Local maintenance deferred: not ready"], WizardUpdate.response)
                say("Host: lease for the stop refused -> busy"); return
            }
            guest = .stopping; status("stopping")
            if mode.hasSuffix("slow") {
                // VM.stop(forceOnTimeout: false): at the end of its budget (played as 1 s) the Host answers failed and
                // keeps the VM stopping; the guest powers off later. The Host stays up and never answers stopped.
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                    try! WizardUpdate.write(["nonce": nonce, "state": "failed", "error": "Clean shutdown timed out"], WizardUpdate.response)
                    say("Host: update clean shutdown timed out; no forced VM stop")
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { guest = .off; status("stopped"); say("guest powered off (late)") }
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                guest = .off; isRunning = false; status("stopped")
                try! WizardUpdate.write(["nonce": nonce, "state": "stopped"], WizardUpdate.response)
                say("Host: guest stopped cleanly, Host quit")
            }
        case "start":
            if isRunning && guest == .off { boot() }
        default: fatalError("unexpected command \(command)")
        }
    }
}

@MainActor func run() throws -> Bool {
    try? FileManager.default.removeItem(at: WizardShared.supportDir)
    try FileManager.default.createDirectory(at: WizardShared.osDir, withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true)
    let disk = WizardShared.osDir.appendingPathComponent("disk.img")
    try Data("DOWNLOADED".utf8).write(to: disk)
    // The journal admitFreshGuestUpdate writes (WizardUpdater.swift).
    try WizardUpdate.write(["kind": "fresh-install", "phase": "installing", "nonce": UUID().uuidString.lowercased(),
        "diskIdentity": WizardDiskIdentity.read(disk)!, "dataHome": WizardShared.supportDir.path,
        "appPath": "/Applications/WizardOS.app", "releaseID": "test-release", "from": "330", "to": "330",
        "guestPatch": true, "applyGuest": true], WizardUpdate.journal)
    try WizardGuestActivation.snapshotStoppedDisk()
    HostControl.releaseLoop()
    var done = false; var result: String? = "unset"
    let activation = WizardGuestActivation()
    activation.onProgress = { say("App: \($0)") }
    activation.onDone = { result = $0; done = true }
    activation.activate()
    let limit = Date().addingTimeInterval(500)
    while !done && Date() < limit { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
    say("activation ended: " + (done ? (result ?? "success") : "NOT ENDED"))
    // The window then (fresh-install onDone -> onGuestFinished -> begin -> connectLocal) asks for its Wizard, twice.
    for wait in [5.0, 3.0] {
        HostControl.ensureRunning(); HostControl.send("start")
        let until = Date().addingTimeInterval(wait)
        while Date() < until { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
    }
    let j = WizardUpdate.json(WizardUpdate.journal)
    let receipt = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))
    let held = FileManager.default.fileExists(atPath: WizardUpdate.maintenanceJournal.path)
    let identity = WizardDiskIdentity.read(disk)
    print("RESULT mode=\(mode) done=\(done) error=\(result ?? "none") phase=\(j["phase"] ?? "-") receiptDisk=\(receipt["diskIdentity"] ?? "-") receiptRelease=\(receipt["releaseID"] ?? "-") guest=\(HostControl.guest.rawValue) leaseHeld=\(held)")
    let activated = done && result == nil && j["phase"] as? String == "guest-activated" && !held && HostControl.guest == .normal
        && receipt["diskIdentity"] as? String == identity && receipt["transactionNonce"] as? String == j["nonce"] as? String
        && receipt["releaseID"] as? String == "test-release"
    switch mode {
    case "ok", "slow", "busy":
        return activated
    default:
        // Not a code-only apply: never recorded as activated, and the receipt is never bound to the disk.
        return done && result != nil && j["phase"] as? String != "guest-activated" && receipt["diskIdentity"] == nil
    }
}
let pass = try MainActor.assumeIsolated { try run() }
print(pass ? "GUEST_ACTIVATION_STOP_\(mode.uppercased())_PASS" : "GUEST_ACTIVATION_STOP_\(mode.uppercased())_FAIL")
exit(pass ? 0 : 1)
