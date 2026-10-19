import Foundation
import Darwin

func log(_ text: String) {}
enum WizardShared {
    static var cold = true
    static var coldBootstrapToken: String? { cold ? "test-cold" : nil }
    static let supportDir = URL(fileURLWithPath: CommandLine.arguments[1])
    static var osDir: URL { supportDir.appendingPathComponent("os") }
    static var logsDir: URL { supportDir }
    static var statusFile: URL { supportDir.appendingPathComponent("status.json") }
    static var guestUpdatePayload: URL? { supportDir }
    static let guestControlPort: UInt32 = 9201
    static let osInstalled = true
}
enum WizardRelease { static let peer = 1 }
enum WizardUpdate {
    static var dir: URL { WizardShared.supportDir.appendingPathComponent("updates") }
    static var journal: URL { dir.appendingPathComponent("transaction.json") }
    static var request: URL { dir.appendingPathComponent("request.json") }
    static var response: URL { dir.appendingPathComponent("response.json") }
    static var maintenanceJournal: URL { dir.appendingPathComponent("maintenance.json") }
    static func json(_ url: URL) -> [String: Any] { (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any] ?? [:] }
    static func write(_ value: [String: Any], _ url: URL) throws { try JSONSerialization.data(withJSONObject:value).write(to:url,options:.atomic) }
    static func error(_ text: String) -> NSError { NSError(domain:"stop-fixture",code:1,userInfo:[NSLocalizedDescriptionKey:text]) }
    static func maintenance(_ nonce: String, _ done: (String?)->Void) { done(nil) }
    static func releaseMaintenance(_ nonce: String) { try? FileManager.default.removeItem(at:maintenanceJournal) }
    static func idle(_ done: (String?)->Void) { fatalError("Normal runtime must never be entered after stop failure") }
}
final class FakeConnection { let fileDescriptor: Int32 = -1; func close() {} }
final class FakeSocket {
    func connect(toPort: UInt32, _ done: (Result<FakeConnection,Error>)->Void) { done(.failure(WizardUpdate.error("I/O fixture"))) }
}
final class FakeMachine {
    var canRequestStop = true
    var forced = 0
    func requestStop() throws {} // never powers off until fixture explicitly signals
    func stop(_ done: (Error?)->Void) { forced += 1; done(nil) }
}
final class VMController {
    enum State { case running, starting, error, stopping, stopped, notInstalled }
    var vm: FakeMachine? = FakeMachine()
    var state: State = .running
    var socketDevice: FakeSocket? = FakeSocket()
    func cancelColdSerialWait() {}
    func cleanupColdSerial() {}
    func signalLateGuestStop() { stopCompletion?() }
// PRODUCTION_STOP
}
@MainActor final class FakeApplication {
    var terminations = 0
    func terminate(_ sender: Any?) { terminations += 1; HostControl.isRunning = false }
}
@MainActor enum ApplicationFixture { static let shared = FakeApplication() }
@MainActor var NSApp: FakeApplication { ApplicationFixture.shared }
@MainActor final class ProductionHost {
    let vm = VMController()
    var preparingUpdate = false, quitting = false
    func send() { prepareUpdate() }
// PRODUCTION_PREPARE
}
@MainActor enum HostControl {
    static var isRunning = false
    static var hasForeignRunner = false
    static var failApply = false
    static var concurrentStop = false
    static var host = ProductionHost()
    static func ensureRunning() { isRunning = true }
    static func waitForLocalWizard(timeout: TimeInterval, tick: (TimeInterval)->Void, done: (Bool)->Void) { done(true) }
    static func send(_ command: String) {
        if command == "apply-guest-update" {
            try! Data("APPLIED".utf8).write(to:WizardShared.osDir.appendingPathComponent("disk.img"))
            let nonce = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-command.json"))["nonce"]!
            try! WizardUpdate.write(["nonce":nonce, "state":failApply ? "failed":"applied", "receipt":["managed_runtime_image":"sha256:fixture"]],WizardUpdate.dir.appendingPathComponent("guest-response.json"))
        } else if command == "prepare-update" {
            if concurrentStop { host.vm.state = .stopping }
            host.send() // actual authenticated production prepareUpdate and stop
        } else { fatalError("unexpected command") }
    }
}
@MainActor func scenario(cold: Bool, failedApply: Bool, concurrent: Bool = false) throws {
    try? FileManager.default.removeItem(at:WizardShared.supportDir)
    try FileManager.default.createDirectory(at:WizardShared.osDir,withIntermediateDirectories:true)
    try FileManager.default.createDirectory(at:WizardUpdate.dir,withIntermediateDirectories:true)
    WizardShared.cold = cold
    HostControl.host = ProductionHost(); HostControl.isRunning = false
    HostControl.failApply = failedApply; HostControl.concurrentStop = concurrent
    NSApp.terminations = 0
    let disk = WizardShared.osDir.appendingPathComponent("disk.img")
    try Data("ORIGINAL".utf8).write(to:disk)
    try WizardUpdate.write(["applyGuest":true,"phase":"installing","kind":cold ? "legacy-cold":"modern","dataHome":WizardShared.supportDir.path,"diskIdentity":WizardDiskIdentity.read(disk)!,"nonce":UUID().uuidString,"releaseID":"fixture"],WizardUpdate.journal)
    try "WIZARD_COLD_FENCED".write(to:WizardShared.logsDir.appendingPathComponent("console.log"),atomically:true,encoding:.utf8)
    try WizardUpdate.write(["token":"held"],WizardUpdate.maintenanceJournal)
    try WizardGuestActivation.snapshotStoppedDisk()
    let machine = HostControl.host.vm.vm!
    let activation = WizardGuestActivation(); var done = false; var error: String?
    activation.onDone = { error = $0; done = true }; activation.activate()
    let deadline = Date().addingTimeInterval(3)
    while !done && Date() < deadline { RunLoop.main.run(until:Date().addingTimeInterval(0.01)) }
    precondition(done && error?.contains("shutdown failed") == true)
    precondition(machine.forced == 0 && HostControl.isRunning && NSApp.terminations == 0)
    precondition(WizardUpdate.json(WizardUpdate.response)["state"] as? String == "failed")
    precondition(WizardUpdate.json(WizardUpdate.journal)["phase"] as? String == "guest-activating")
    let actualDisk = try String(contentsOf:disk,encoding:.utf8)
    let backup = try String(contentsOf:WizardGuestActivation.backup,encoding:.utf8)
    precondition(actualDisk == "APPLIED" && backup == "ORIGINAL")
    precondition(!FileManager.default.fileExists(atPath:WizardUpdate.dir.appendingPathComponent("legacy-complete.json").path))
    precondition(WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-receipt.json"))["diskIdentity"] == nil)
    if cold { precondition(FileManager.default.fileExists(atPath:WizardUpdate.maintenanceJournal.path)) }
    // The timed-out VM can finish later, but must never overwrite the failed reply.
    HostControl.host.vm.signalLateGuestStop()
    precondition(WizardUpdate.json(WizardUpdate.response)["state"] as? String == "failed")
    precondition(NSApp.terminations == 0 && machine.forced == 0)
    print("STOP_FAILURE_PRESERVES_OWNERSHIP_BACKUP_NO_ACTIVATION_PASS cold=\(cold) applyFailure=\(failedApply) concurrent=\(concurrent)")
}
@MainActor func cleanStop(cold: Bool) throws {
    WizardShared.cold = cold; HostControl.host = ProductionHost(); HostControl.isRunning = true
    NSApp.terminations = 0
    let machine = HostControl.host.vm.vm!
    let nonce = UUID().uuidString
    try WizardUpdate.write(["nonce":nonce,"pid":getpid(),"appPath":Bundle.main.bundleURL.standardizedFileURL.path,
                            "peer":WizardRelease.peer,"expires":Date().addingTimeInterval(30).timeIntervalSince1970],WizardUpdate.request)
    HostControl.host.send(); HostControl.host.vm.signalLateGuestStop()
    precondition(WizardUpdate.json(WizardUpdate.response)["state"] as? String == "stopped")
    precondition(WizardUpdate.json(WizardUpdate.response)["nonce"] as? String == nonce)
    precondition(NSApp.terminations == 1 && machine.forced == 0 && HostControl.host.quitting)
    print("ACTUAL_PREPARE_CLEAN_STOP_PASS cold=\(cold)")
}
try MainActor.assumeIsolated {
    for cold in [false,true] {
        for failed in [false,true] { try scenario(cold:cold,failedApply:failed) }
    }
    try scenario(cold:true,failedApply:false,concurrent:true)
    try cleanStop(cold:false); try cleanStop(cold:true)
    print("UPDATE_SHUTDOWN_SCENARIOS_PASS 7")
}
