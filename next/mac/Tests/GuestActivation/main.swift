import AppKit
import Darwin

// Link the production WizardGuestActivation.swift, replacing only its I/O peers.
// A real APFS clone/rename checks rollback; no VM or user data is used here.
enum WizardShared {
    static let supportDir = URL(fileURLWithPath: CommandLine.arguments[1])
    static var osDir: URL { supportDir.appendingPathComponent("os") }
    static var statusFile: URL { supportDir.appendingPathComponent("host-status.json") }
    static let osInstalled = true
    static var guestUpdatePayload: URL? { supportDir }
}
enum WizardRelease { static let peer = 1 }
enum WizardUpdate {
    static var dir: URL { WizardShared.supportDir.appendingPathComponent("updates") }
    static var journal: URL { dir.appendingPathComponent("transaction.json") }
    static var request: URL { dir.appendingPathComponent("request.json") }
    static var response: URL { dir.appendingPathComponent("response.json") }
    static var maintenanceJournal: URL { dir.appendingPathComponent("maintenance.json") }
    static var heldHealthCalls = 0
    static var normalHealthCalls = 0
    static func json(_ url: URL) -> [String: Any] { (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any] ?? [:] }
    static func write(_ value: [String: Any], _ url: URL) throws { try JSONSerialization.data(withJSONObject: value).write(to: url, options: .atomic) }
    static func error(_ text: String) -> NSError { NSError(domain: "activation-test", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
    static func idle(_ done: @escaping (String?) -> Void) {
        if FileManager.default.fileExists(atPath: maintenanceJournal.path) { heldHealthCalls += 1; done("deliberately stopped for maintenance") }
        else { normalHealthCalls += 1; done(normalHealthCalls == 1 ? "runtime still reconnecting" : nil) }
    }
}
@MainActor enum HostControl {
    static var isRunning = false
    static var failAfterApply = false
    static func ensureRunning() {
        isRunning = true
        try! WizardUpdate.write(["state": "running"], WizardShared.statusFile)
        if WizardUpdate.json(WizardUpdate.journal)["phase"] as? String != "guest-activating" {
            // Reconnection cannot be accepted before the Host's release completes.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { try! FileManager.default.removeItem(at: WizardUpdate.maintenanceJournal) }
        }
    }
    static func waitForLocalWizard(timeout: TimeInterval, tick: @escaping (TimeInterval) -> Void, done: @escaping (Bool) -> Void) { done(true) }
    static func send(_ command: String) {
        if command == "apply-guest-update" {
            let nonce = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-command.json"))["nonce"]!
            try! Data("APPLIED".utf8).write(to: WizardShared.osDir.appendingPathComponent("disk.img"))
            let reply: [String: Any] = failAfterApply ? ["nonce": nonce, "state": "failed", "error": "injected post-apply failure"] : ["nonce": nonce, "state": "applied", "receipt": ["authenticatedByHost": true]]
            try! WizardUpdate.write(reply, WizardUpdate.dir.appendingPathComponent("guest-response.json"))
        } else if command == "prepare-update" {
            isRunning = false
            try! WizardUpdate.write(["state": "stopped"], WizardShared.statusFile)
            try! WizardUpdate.write(["nonce": WizardUpdate.json(WizardUpdate.request)["nonce"]!, "state": "stopped"], WizardUpdate.response)
        } else { fatalError("unexpected command") }
    }
}
@MainActor func scenario(_ fail: Bool) throws {
    HostControl.isRunning = false; HostControl.failAfterApply = fail
    WizardUpdate.heldHealthCalls = 0; WizardUpdate.normalHealthCalls = 0
    try? FileManager.default.removeItem(at: WizardShared.supportDir)
    try FileManager.default.createDirectory(at: WizardShared.osDir, withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true)
    try Data("ORIGINAL".utf8).write(to: WizardShared.osDir.appendingPathComponent("disk.img"))
    try WizardUpdate.write(["applyGuest": true, "phase": "installing"], WizardUpdate.journal)
    try WizardUpdate.write(["token": "test-owner"], WizardUpdate.maintenanceJournal)
    try WizardGuestActivation.snapshotStoppedDisk()
    var done = false; var result: String?
    let activation = WizardGuestActivation()
    activation.onDone = { result = $0; done = true }
    activation.activate()
    let deadline = Date().addingTimeInterval(5)
    while !done && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
    precondition(done, "bounded completion")
    precondition(WizardUpdate.heldHealthCalls == 0, "never demand live-agent health under held admission")
    precondition(WizardUpdate.normalHealthCalls > 0, "require real normal-runtime health")
    precondition(!FileManager.default.fileExists(atPath: WizardUpdate.maintenanceJournal.path))
    let disk = try String(contentsOf: WizardShared.osDir.appendingPathComponent("disk.img"), encoding: .utf8)
    precondition(disk == (fail ? "ORIGINAL" : "APPLIED"))
    precondition(fail ? result?.contains("Prior guest restored") == true : result == nil)
    print(fail ? "POST_APPLY_ROLLBACK_SAME_DISK_PASS" : "HELD_APPLY_NORMAL_RECONNECT_PASS")
}
try MainActor.assumeIsolated {
    try scenario(false)
    try scenario(true)
}
