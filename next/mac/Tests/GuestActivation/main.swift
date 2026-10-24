import AppKit
import Darwin

// Link the production WizardGuestActivation.swift, replacing only its I/O peers.
// A real APFS clone/rename checks rollback; no VM or user data is used here.
enum WizardShared {
    static var cold = false
    static var coldBootstrapToken: String? { cold && WizardUpdate.json(WizardUpdate.journal)["phase"] as? String == "guest-activating" ? "test-cold" : nil }
    static var logsDir: URL { supportDir }
    static let supportDir = URL(fileURLWithPath: CommandLine.arguments[1])
    static var osDir: URL { supportDir.appendingPathComponent("os") }
    static var statusFile: URL { supportDir.appendingPathComponent("host-status.json") }
    static let osInstalled = true
    static var diskIdentity: String { WizardDiskIdentity.read(osDir.appendingPathComponent("disk.img")) ?? "unknown" }
    static var guestUpdatePayload: URL? { supportDir }
}
struct WizardRelease {
    static let peer = 1
    let releaseID = "test-release"; let build = "309"; let payloadID: String? = "sha256:fixture"
    static func read(_ app: URL) throws -> WizardRelease { WizardRelease() }
    func validate(_ app: URL) throws {}
}
// I/O fixtures only; actual ABI policy is compiled by test_os_manifest_contract.py.
enum WizardGuestABI {
    static func image(_ manifest: [String: Any]) throws -> Int { 1 }
    static func payload(_ url: URL, abi: Int) throws {}
    static func requiresFreshApply(baked: String?, bundled: String?) -> Bool { baked == nil || baked != bundled }
    static func requireSystemOwner(_ receipt: [String: Any], diskIdentity: String, incomingBuild: String) throws {}
}
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
    static var hasForeignRunner = false
    static var failAfterApply = false
    static var replacementOnStop = false
    static func ensureRunning() {
        isRunning = true
        if WizardShared.coldBootstrapToken != nil {
            // Like the real Host: only this launch may produce a verdict.
            // Synchronous output also covers a boot faster than ensureRunning.
            try! "WIZARD_COLD_FENCED".write(to: WizardShared.logsDir.appendingPathComponent("console.log"), atomically: true, encoding: .utf8)
        }
        try! WizardUpdate.write(["state": "running"], WizardShared.statusFile)
        if WizardUpdate.json(WizardUpdate.journal)["phase"] as? String != "guest-activating" {
            // Reconnection cannot be accepted before the Host's release completes.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { try! FileManager.default.removeItem(at: WizardUpdate.maintenanceJournal) }
        }
    }
    static func waitForLocalWizard(timeout: TimeInterval, tick: @escaping (TimeInterval) -> Void, done: @escaping (Bool) -> Void) { done(true) }
    static func send(_ command: String) {
        if command == "verify-apps-after-update" {
            try! WizardUpdate.write(["nonce": WizardUpdate.json(WizardUpdate.journal)["nonce"]!, "ok":true], WizardUpdate.dir.appendingPathComponent("apps-health.json"))
        } else if command == "apply-guest-update" {
            let nonce = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-command.json"))["nonce"]!
            try! Data("APPLIED".utf8).write(to: WizardShared.osDir.appendingPathComponent("disk.img"))
            let reply: [String: Any] = failAfterApply ? ["nonce": nonce, "state": "failed", "error": "injected post-apply failure"] : ["nonce": nonce, "state": "applied", "receipt": ["authenticatedByHost": true, "managed_runtime_image": "sha256:test"]]
            try! WizardUpdate.write(reply, WizardUpdate.dir.appendingPathComponent("guest-response.json"))
        } else if command == "prepare-update" {
            if replacementOnStop { try! Data("CHANGED_AT_COMPLETION".utf8).write(to: WizardShared.osDir.appendingPathComponent("disk.img"), options: .atomic) }
            isRunning = false
            try! WizardUpdate.write(["state": "stopped"], WizardShared.statusFile)
            try! WizardUpdate.write(["nonce": WizardUpdate.json(WizardUpdate.request)["nonce"]!, "state": "stopped"], WizardUpdate.response)
        } else { fatalError("unexpected command") }
    }
}
@MainActor func scenario(_ fail: Bool, cold: Bool = false, replacementOnStop: Bool = false) throws {
    WizardShared.cold = cold
    HostControl.isRunning = false; HostControl.failAfterApply = fail; HostControl.replacementOnStop = replacementOnStop
    WizardUpdate.heldHealthCalls = 0; WizardUpdate.normalHealthCalls = 0
    try? FileManager.default.removeItem(at: WizardShared.supportDir)
    try FileManager.default.createDirectory(at: WizardShared.osDir, withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true)
    try Data("ORIGINAL".utf8).write(to: WizardShared.osDir.appendingPathComponent("disk.img"))
    try WizardUpdate.write(["applyGuest": true, "phase": "installing", "kind": cold ? "legacy-cold" : "modern", "dataHome": WizardShared.supportDir.path, "diskIdentity": WizardDiskIdentity.read(WizardShared.osDir.appendingPathComponent("disk.img"))!, "nonce": UUID().uuidString, "releaseID": "test-release"], WizardUpdate.journal)
    try WizardUpdate.write(["token": "test-owner"], WizardUpdate.maintenanceJournal)
    let originalIdentity = WizardDiskIdentity.read(WizardShared.osDir.appendingPathComponent("disk.img"))!
    try WizardGuestActivation.snapshotStoppedDisk()
    var done = false; var result: String?
    let activation = WizardGuestActivation()
    activation.onDone = { result = $0; done = true }
    activation.activate()
    let deadline = Date().addingTimeInterval(5)
    while !done && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
    precondition(done, "bounded completion")
    if replacementOnStop {
        precondition(result?.contains("identity changed") == true)
        precondition(!HostControl.isRunning && WizardUpdate.normalHealthCalls == 0)
        let unchangedBackup = try String(contentsOf: WizardGuestActivation.backup, encoding: .utf8)
        let replacement = try String(contentsOf: WizardShared.osDir.appendingPathComponent("disk.img"), encoding: .utf8)
        precondition(unchangedBackup == "ORIGINAL" && replacement == "CHANGED_AT_COMPLETION")
        precondition(WizardUpdate.json(WizardUpdate.journal)["phase"] as? String == "guest-activating")
        precondition(WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))["diskIdentity"] == nil)
        precondition(!FileManager.default.fileExists(atPath: WizardUpdate.dir.appendingPathComponent("legacy-complete.json").path))
        print("COLD_CHANGED_INODE_COMPLETION_REFUSED_PASS")
        return
    }
    precondition(WizardUpdate.heldHealthCalls == 0, "never demand live-agent health under held admission")
    precondition(fail && cold ? WizardUpdate.normalHealthCalls == 0 : WizardUpdate.normalHealthCalls > 0, "cold rollback stays stopped; success requires normal health")
    if fail && cold { precondition(!HostControl.isRunning) }
    precondition(!FileManager.default.fileExists(atPath: WizardUpdate.maintenanceJournal.path))
    let disk = try String(contentsOf: WizardShared.osDir.appendingPathComponent("disk.img"), encoding: .utf8)
    precondition(disk == (fail ? "ORIGINAL" : "APPLIED"))
    precondition(fail ? result?.contains("Prior guest restored") == true : result == nil)
    if cold && fail {
        let journal = WizardUpdate.json(WizardUpdate.journal)
        let transition = journal["rollbackIdentityTransition"] as! [String: String]
        precondition(transition["from"] == originalIdentity)
        precondition(transition["to"] == WizardDiskIdentity.read(WizardShared.osDir.appendingPathComponent("disk.img")))
        precondition(transition["from"] != transition["to"])
        precondition(journal["diskIdentity"] as? String == transition["to"])
        print("COLD_ROLLBACK_IDENTITY_TRANSITION_PASS")
    }
    if cold && !fail { try completionRelaunch() }
    print((cold ? "COLD_" : "") + (fail ? "POST_APPLY_ROLLBACK_SAME_DISK_PASS" : "HELD_APPLY_NORMAL_RECONNECT_PASS"))
}
@MainActor func completionRelaunch() throws {
    let disk = WizardShared.osDir.appendingPathComponent("disk.img")
    let journal = WizardUpdate.json(WizardUpdate.journal)
    let receipt = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))
    let completion = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("legacy-complete.json"))
    func admitted(_ complete: [String: Any], _ modern: [String: Any]) -> Bool {
        WizardDiskIdentity.completed(complete, modern: modern, journal: journal, disk: disk, home: WizardShared.supportDir)
    }
    precondition(admitted(completion, receipt), "same disk repeat launch")
    precondition(admitted([:], receipt), "bound fallback survives missing completion file")
    precondition(!admitted([:], ["managed_runtime_image": "sha256:old"]), "old unbound fallback cannot admit")
    var wrongNonce = receipt; wrongNonce["transactionNonce"] = "other"
    precondition(!admitted([:], wrongNonce))
    HostControl.isRunning = false // simulate stopped app before external restore
    let ownership = WizardDiskOwnership(); try ownership.acquire(); defer { ownership.release() }
    let boundCompletion = try WizardDiskIdentity.completionRecord(journal)
    precondition(boundCompletion["diskIdentity"] as? String == journal["diskIdentity"] as? String)
    try Data("RESTORED_LEGACY".utf8).write(to: disk, options: .atomic)
    precondition(WizardDiskIdentity.read(disk) != journal["diskIdentity"] as? String, "fixture actually changes inode")
    precondition(!admitted(completion, receipt), "stale complete file cannot admit replacement")
    precondition(!admitted([:], receipt), "bound fallback cannot admit replacement")
    do { _ = try WizardDiskIdentity.completionRecord(journal); fatalError("minted completion for changed disk") }
    catch { precondition(error.localizedDescription.contains("identity changed")) }
    print("COLD_COMPLETION_RELAUNCH_EXACT_DISK_PASS")
}

@MainActor func changedDiskRecovery(lockHeld: Bool = false) throws {
    HostControl.isRunning = false; WizardShared.cold = true
    try? FileManager.default.removeItem(at: WizardShared.supportDir)
    try FileManager.default.createDirectory(at: WizardShared.osDir, withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: WizardUpdate.dir, withIntermediateDirectories: true)
    let disk = WizardShared.osDir.appendingPathComponent("disk.img")
    try Data("INTERRUPTED".utf8).write(to: disk)
    let identity = WizardDiskIdentity.read(disk)!
    try WizardGuestActivation.snapshotStoppedDisk()
    try WizardUpdate.write(["kind":"legacy-cold", "phase":"guest-activating", "diskIdentity":identity, "dataHome":WizardShared.supportDir.path], WizardUpdate.journal)
    try WizardUpdate.write(["token":"retain"], WizardUpdate.maintenanceJournal)
    let restored = WizardUpdate.dir.appendingPathComponent("restore-disk.img")
    try Data("STAGING_MUST_SURVIVE".utf8).write(to: restored)
    if !lockHeld { try Data("REPLACEMENT".utf8).write(to: disk, options: .atomic) }
    precondition(lockHeld || WizardDiskIdentity.read(disk) != identity)
    let paths = [disk, WizardGuestActivation.backup, restored, WizardUpdate.journal, WizardUpdate.maintenanceJournal]
    let bytes = try paths.map { try Data(contentsOf:$0) }
    let identities = paths.map { WizardDiskIdentity.read($0) }
    let ownership = WizardDiskOwnership()
    if lockHeld { try ownership.acquire() }
    defer { ownership.release() }
    let activation = WizardGuestActivation(); var done = false; var result: String?
    activation.onDone = { result = $0; done = true }
    activation.recoverInterruptedActivation()
    precondition(done && result?.contains(lockHeld ? "Another process owns" : "identity changed") == true)
    precondition(!HostControl.isRunning)
    for (index, path) in paths.enumerated() {
        let actual = try Data(contentsOf:path)
        precondition(actual == bytes[index], "refusal must not overwrite any recovery file")
        precondition(WizardDiskIdentity.read(path) == identities[index])
    }
    print(lockHeld ? "COLD_RECOVERY_OWNERSHIP_LOCK_PASS" : "COLD_CHANGED_INODE_RECOVERY_NO_WRITES_PASS")
}

try MainActor.assumeIsolated {
    try scenario(false)
    try scenario(true)
    try scenario(false, cold: true)
    try scenario(true, cold: true)
    try scenario(false, cold: true, replacementOnStop: true)
    try changedDiskRecovery()
    try changedDiskRecovery(lockHeld: true)
}
