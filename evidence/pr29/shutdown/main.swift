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
    final class FakeColdSerial { var delivered = true }
    var coldSerial: FakeColdSerial? = nil // production stop() checks it for an unbooted cold maintenance VM
    func cancelColdSerialWait() {}
    func cleanupColdSerial() {}
    func signalLateGuestStop() { stopCompletion?() }
    func stop(completion: (() -> Void)? = nil) { stop(forceOnTimeout: true, completion: completion) }
    func stop(forceOnTimeout: Bool, onTimeout: (() -> Void)? = nil, completion: (() -> Void)? = nil) {
        guard let machine = vm else { completion?(); return }
        guard state == .running || state == .starting || state == .error else {
            // A concurrent shutdown is not evidence that the disk is stopped.
            onTimeout?(); return
        }
        // A cold maintenance boot whose bootstrap command was never sent has run only the kernel and the bare
        // PID1 shell. Nothing listens on the control port there, so a clean poweroff can never arrive and the
        // update path (no forced stop) used to sit in "stopping" forever. Nothing in the guest has written to
        // the disk, and a failed activation restores the stopped-disk rollback clone anyway: stop it directly.
        let idleColdBoot = coldSerial.map { !$0.delivered } ?? false
        cancelColdSerialWait()
        state = .stopping
        log("stopping Wizard OS")
        var finished = false
        var timedOut = false
        let done = { [weak self] in
            guard !finished, self?.vm === machine else { return }
            finished = true
            self?.stopCompletion = nil
            self?.cleanupColdSerial()
            self?.vm = nil; self?.socketDevice = nil
            self?.state = .stopped
            // A late guest stop must not overwrite a terminal update failure.
            if !timedOut { completion?() }
        }
        stopCompletion = done
        if idleColdBoot {
            log("maintenance boot never received its command; stopping it directly")
            machine.stop { error in
                DispatchQueue.main.async {
                    guard error == nil else {
                        log("maintenance boot stop failed: \(error!.localizedDescription)")
                        try? WizardUpdate.write(["nonce": WizardUpdate.json(WizardUpdate.request)["nonce"] ?? "", "state": "failed", "error": "VM stop failed; disk retained"], WizardUpdate.response)
                        onTimeout?(); return
                    }
                    done()
                }
            }
            return
        }
        // Ask Wizard OS to power off cleanly; force-stop if it hasn't within 90 s (Docker stops every app first).
        socketDevice?.connect(toPort: WizardShared.guestControlPort) { result in
            if case .success(let conn) = result {
                _ = "poweroff\n".withCString { write(conn.fileDescriptor, $0, 9) }
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { conn.close() }
            } else if machine.canRequestStop {
                try? machine.requestStop()
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.01) {
            guard !finished else { return }
            if !forceOnTimeout {
                timedOut = true
                log("update clean shutdown timed out; keeping prior Host, no forced VM stop")
                try? WizardUpdate.write(["nonce": WizardUpdate.json(WizardUpdate.request)["nonce"] ?? "", "state": "failed", "error": "Clean shutdown timed out"], WizardUpdate.response)
                onTimeout?()
                return
            }
            log("clean shutdown timed out; forcing stop")
            machine.stop { error in
                DispatchQueue.main.async {
                    guard error == nil else {
                        try? WizardUpdate.write(["nonce": WizardUpdate.json(WizardUpdate.request)["nonce"] ?? "", "state": "failed", "error": "VM stop failed; disk retained"], WizardUpdate.response)
                        onTimeout?(); return
                    }
                    done()
                }
            }
        }
    }
    private var stopCompletion: (() -> Void)?


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
    private func prepareUpdate() {
        guard !preparingUpdate else { return }
        let request = WizardUpdate.json(WizardUpdate.request)
        let enclosingApp = Bundle.main.bundleURL.standardizedFileURL.path
        guard let nonce = request["nonce"] as? String, UUID(uuidString: nonce) != nil,
              let pid = request["pid"] as? Int32, kill(pid, 0) == 0,
              request["appPath"] as? String == enclosingApp,
              request["peer"] as? Int == WizardRelease.peer,
              let expires = request["expires"] as? Double, expires > Date().timeIntervalSince1970 else { return }
        preparingUpdate = true
        let stopWhenIdle: (String?) -> Void = { [weak self] reason in
            guard let self else { return }
            if let reason { self.preparingUpdate = false; try? WizardUpdate.write(["nonce": nonce, "state": "busy", "error": reason], WizardUpdate.response); return }
            self.vm.stop(forceOnTimeout: false, onTimeout: {
                try? WizardUpdate.write(["nonce": nonce, "state": "failed", "error": "Clean shutdown not confirmed; rollback disk retained"], WizardUpdate.response)
                if WizardShared.coldBootstrapToken == nil { WizardUpdate.releaseMaintenance(nonce) }
                self.preparingUpdate = false
            }) {
                try? WizardUpdate.write(["nonce": nonce, "state": "stopped", "build": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") ?? "", "dataHome": WizardShared.supportDir.path], WizardUpdate.response)
                self.quitting = true
                NSApp.terminate(nil)
            }
        }
        if self.vm.state == .stopped || self.vm.state == .notInstalled || WizardShared.coldBootstrapToken != nil { stopWhenIdle(nil) }
        else { WizardUpdate.maintenance(nonce, stopWhenIdle) }
    }


}
@MainActor enum HostControl {
    static var isRunning = false
    static var hasForeignRunner = false
    static var failApply = false
    static var concurrentStop = false
    static var host = ProductionHost()
    static func ensureRunning() {
        isRunning = true
        if WizardShared.coldBootstrapToken != nil {
            try! "WIZARD_COLD_FENCED".write(to:WizardShared.logsDir.appendingPathComponent("console.log"),atomically:true,encoding:.utf8)
        }
    }
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
