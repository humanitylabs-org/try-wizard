import Foundation
import Darwin
import Virtualization

// CLI-only I/O adapters. VM, activation, identity, patch and maintenance HTTP code
// are linked unchanged (except explicit root and guest-open-URL refusal; provenance).
let env = ProcessInfo.processInfo.environment
let candidateApp = URL(fileURLWithPath: env["WIZARD_HEADLESS_APP"]!)
let mode = env["WIZARD_HEADLESS_MODE"]!
let output = URL(fileURLWithPath: env["WIZARD_HEADLESS_OUTPUT"]!)
var leaseFD: Int32 = -1
var preparing = false, activatingGuest = false, qaBusy = false
func isRecording() -> Bool { false } // no capture device or capture client in this CLI
func onFreeze(_ freeze: Bool) {}
var finished = false
var exitStatus: Int32 = 1
var result: [String: Any] = ["mode":mode, "realVM":true, "physicalConsent":false,
    "consent":"test-authorized stopped admission adapter", "preferencesTouched":false,
    "GUIStarted":false, "productionReleaseID":"98049a6cdc7285e10cf8c66e41b769e40cffc508"]
func record(_ key: String, _ value: Any) {
    result[key] = value
    try? JSONSerialization.data(withJSONObject: result, options:[.prettyPrinted,.sortedKeys]).write(to:output.appendingPathComponent("result.json"),options:.atomic)
}
func diskHolders() -> [Int32]? {
    let p = Process(), pipe = Pipe()
    p.executableURL = URL(fileURLWithPath:"/usr/sbin/lsof")
    p.arguments = ["-t", WizardShared.osDir.appendingPathComponent("disk.img").path]
    p.standardOutput = pipe; p.standardError = FileHandle.nullDevice
    do {
        try p.run(); let data = pipe.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
        guard p.terminationStatus == 0 || p.terminationStatus == 1 else { return nil }
        return String(data:data,encoding:.utf8)!.split(separator:"\n").compactMap { Int32($0) }
    } catch { return nil }
}
@MainActor enum HostControl {
    static let vm = VMController()
    static let owner = WizardDiskOwnership()
    static var running = false
    static var isRunning: Bool { running }
    static var hasForeignRunner: Bool { diskHolders().map { $0.contains(where: { $0 != getpid() }) } ?? true }
    static var bridges: [LoopbackBridge] = []
    static var releaseTimer: Timer?
    static func ensureRunning() {
        guard !running else { return }
        do {
            guard !hasForeignRunner else { throw WizardUpdate.error("Foreign disk descriptor") }
            try owner.acquire()
            running = true
            if bridges.isEmpty {
                bridges = [LoopbackBridge(hostPort:WizardShared.uxPort,guestPort:WizardShared.guestUXPort,vm:vm),
                           LoopbackBridge(hostPort:WizardShared.setupPort,guestPort:WizardShared.guestSetupPort,vm:vm)]
                bridges.forEach { $0.start() }
            }
            vm.start()
            releaseTimer?.invalidate()
            releaseTimer = Timer.scheduledTimer(withTimeInterval:3,repeats:true) { _ in
                if vm.state == .running && WizardShared.guestUpdatePayload == nil,
                   let token = WizardUpdate.json(WizardUpdate.maintenanceJournal)["token"] as? String {
                    WizardUpdate.releaseMaintenance(token)
                }
            }
        } catch { end(error.localizedDescription) }
    }
    static func waitForLocalWizard(timeout: TimeInterval, tick: @escaping (TimeInterval)->Void, done: @escaping (Bool)->Void) {
        let deadline = Date().addingTimeInterval(timeout)
        func poll() {
            if vm.state == .running { done(true); return }
            if vm.state == .error || Date() > deadline { done(false); return }
            tick(deadline.timeIntervalSinceNow)
            DispatchQueue.main.asyncAfter(deadline:.now()+1,execute:poll)
        }
        poll()
    }
    static func closed(_ done: @escaping (Bool)->Void) {
        // Production stop retains its VZ machine in the 90s timeout closure.
        // Do NOT release ownership or restore while any image descriptor remains.
        let deadline = Date().addingTimeInterval(110)
        func poll() {
            if vm.canTerminateWithoutStopping, let holders = diskHolders(), holders.isEmpty {
                let serial = WizardShared.logsDir.appendingPathComponent("console.log")
                if FileManager.default.fileExists(atPath:serial.path) {
                    try? FileManager.default.copyItem(at:serial,to:output.appendingPathComponent("console-stopped-"+UUID().uuidString+".log"))
                }
                running = false; owner.release(); record("lastStopDescriptorsClosed",true); done(true); return
            }
            if Date() > deadline { record("stopDescriptorTimeout",true); done(false); return }
            DispatchQueue.main.asyncAfter(deadline:.now()+1,execute:poll)
        }
        poll()
    }
    static func stop(_ done: @escaping (Bool)->Void) {
        releaseTimer?.invalidate()
        guard running else { closed(done); return }
        // Stricter than the cold production timeout: a force-stop cannot pass QA.
        vm.stop(forceOnTimeout:false,onTimeout:{ done(false) }) { closed(done) }
    }
    static func send(_ command: String) {
        if command == "prepare-update" {
            let nonce = WizardUpdate.json(WizardUpdate.request)["nonce"] as? String ?? ""
            stop { ok in
                try? WizardUpdate.write(["nonce":nonce,"state":ok ? "stopped":"failed"],WizardUpdate.response)
            }
        } else if command == "apply-guest-update" {
            let nonce = WizardUpdate.json(WizardUpdate.dir.appendingPathComponent("guest-command.json"))["nonce"] as? String ?? ""
            audit("cold-before") { before in
                guard before else { patchReply(nonce,nil,"Cold prestate audit failed"); return }
                vm.runGuestPatch { receipt in
                    guard let receipt else { patchReply(nonce,nil,"Production patch returned no receipt"); return }
                    record("productionGuestReceipt",receipt)
                    let fence = receipt["cold_bootstrap"] as? [String:Any] ?? [:]
                    guard fence["executionFenceHeldAfterCommit"] as? Bool == true,
                          Set(fence["postCommitDeniedRoutes"] as? [String] ?? []).isSuperset(of:["create","start","exec"]) else {
                        patchReply(nonce,nil,"Missing production fence proof"); return
                    }
                    audit("cold-after") { after in
                        if !after { patchReply(nonce,nil,"Post-apply audit failed"); return }
                        if mode == "fault" {
                            record("faultInjectedAfterRealApply",true)
                            patchReply(nonce,nil,"QA injected post-apply response fault (sealed payload unchanged)")
                        } else { patchReply(nonce,receipt,nil) }
                    }
                }
            }
        } else { end("Unexpected command "+command) }
    }
    static func patchReply(_ nonce:String,_ receipt:[String:Any]?,_ error:String?) {
        var r:[String:Any] = ["nonce":nonce,"state":receipt == nil ? "failed":"applied"]
        if let receipt { r["receipt"] = receipt }; if let error { r["error"] = error }
        try? WizardUpdate.write(r,WizardUpdate.dir.appendingPathComponent("guest-response.json"))
    }
}

// Private VZ connection only. No root shell TCP listener is ever created.
@MainActor func shell(_ script:String, timeout:TimeInterval = 120, done:@escaping (String?)->Void) {
    let deadline = Date().addingTimeInterval(timeout)
    func connect() {
        guard let device = HostControl.vm.socketDevice else { done(nil); return }
        device.connect(toPort:WizardShared.guestDevShellPort) { response in
            switch response {
            case .failure:
                if Date() < deadline { DispatchQueue.main.asyncAfter(deadline:.now()+1,execute:connect) }
                else { done(nil) }
            case .success(let connection):
                var completed = false
                let finish:(String?)->Void = { text in
                    guard !completed else { return }; completed = true; connection.close(); done(text)
                }
                DispatchQueue.main.asyncAfter(deadline:.now()+timeout) { finish(nil) }
                DispatchQueue.global().async {
                    let handle = FileHandle(fileDescriptor:connection.fileDescriptor,closeOnDealloc:false)
                    do {
                        try handle.write(contentsOf:Data((script+"\nexit\n").utf8))
                        let bytes = try handle.readToEnd() ?? Data()
                        let text = String(data:bytes,encoding:.utf8)
                        DispatchQueue.main.async { finish(text) }
                    } catch { DispatchQueue.main.async { finish(nil) } }
                }
            }
        }
    }
    connect()
}
@MainActor func audit(_ name:String,_ done:@escaping (Bool)->Void) {
    guard let script = try? String(contentsOf:URL(fileURLWithPath:env["WIZARD_HEADLESS_AUDIT"]!),encoding:.utf8) else { done(false); return }
    shell(script, timeout: 360) { text in
        guard let text, let line = text.split(separator:"\n").first(where:{$0.hasPrefix("HEADLESS_AUDIT ")}),
              let data = String(line.dropFirst("HEADLESS_AUDIT ".count)).data(using:.utf8),
              let document = try? JSONSerialization.jsonObject(with:data) as? [String:Any] else {
            record(name+"Error", "Private vsock audit failed; no successful receipt")
            // Auditor never prints credentials; bounded output is still kept private.
            try? text?.write(to:output.appendingPathComponent(name+"-error.log"),atomically:true,encoding:.utf8)
            done(false); return
        }
        try? data.write(to:output.appendingPathComponent(name+".json"),options:.atomic)
        record(name+"Captured",true); done(true)
    }
}
var ending = false
@MainActor func end(_ error:String?) {
    guard !ending else { return }; ending = true
    if let error { record("error",error) }
    HostControl.stop { stopped in
        record("stopped",stopped)
        record("success",error == nil && stopped)
        exitStatus = error == nil && stopped ? 0 : 1
        if leaseFD >= 0 { flock(leaseFD,LOCK_UN); close(leaseFD); leaseFD = -1 }
        finished = true
    }
}
@MainActor func normal(_ name:String) {
    HostControl.ensureRunning()
    HostControl.waitForLocalWizard(timeout:300,tick:{_ in}) { ready in
        guard ready else { end("Normal boot not ready"); return }
        audit(name) { ok in end(ok ? nil : "Normal audit failed") }
    }
}
@MainActor func begin() {
    record("startedAt",Date().timeIntervalSince1970)
    if mode == "reject-disk" {
        WizardGuestActivation.shared.onDone = { error in
            guard let error, error.contains("disk identity changed") else { end("Changed disk was not refused"); return }
            record("changedDiskRefused",true); end(nil)
        }
        WizardGuestActivation.shared.recoverInterruptedActivation(); return
    }
    guard mode == "baseline" || mode == "normal" || mode == "upgrade" || mode == "fault" || mode == "repeat" else { end("Unknown mode"); return }
    if mode == "baseline" || mode == "normal" { normal(mode); return }
    if mode == "repeat" {
        guard !WizardShared.legacyBootstrapNeeded else { end("Repeat admission was not a no-op"); return }
        record("repeatAdmissionNoop",true); normal("repeat"); return
    }
    do {
        guard WizardShared.legacyBootstrapNeeded else { throw WizardUpdate.error("Expected unprimed legacy disk") }
        try admitStopped()
        WizardGuestActivation.shared.onProgress = { log($0) }
        WizardGuestActivation.shared.onDone = { error in
            let journal = WizardUpdate.json(WizardUpdate.journal)
            record("activationJournal",journal)
            if mode == "fault" {
                guard journal["phase"] as? String == "guest-rolled-back",
                      result["faultInjectedAfterRealApply"] as? Bool == true,
                      !HostControl.isRunning else { end(error ?? "Fault rollback not verified"); return }
                record("productionRollbackCompleted",true); end(nil)
            } else {
                guard error == nil else { end(error); return }
                guard !WizardShared.legacyBootstrapNeeded else { end("Completion binding missing"); return }
                audit("normal-after") { ok in end(ok ? nil : "Post-upgrade audit failed") }
            }
        }
        WizardGuestActivation.shared.activate()
    } catch { end(error.localizedDescription) }
}
signal(SIGPIPE,SIG_IGN)
var signalSources: [DispatchSourceSignal] = []
for sig in [SIGTERM,SIGINT] {
    signal(sig,SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal:sig,queue:.main)
    source.setEventHandler { Task { @MainActor in end("Worker cancellation") } }; source.resume(); signalSources.append(source)
}
DispatchQueue.main.async { begin() }
DispatchQueue.main.asyncAfter(deadline:.now()+2100) { end("Bounded CLI deadline") }
while !finished { RunLoop.main.run(until:Date().addingTimeInterval(0.1)) }
exit(exitStatus)
