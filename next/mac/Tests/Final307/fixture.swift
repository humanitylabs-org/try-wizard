// Linked against the ENTIRE unchanged production WizardUpdater.swift.
// AppKit is real; collaborators below are explicit policy test adapters.
// No VM, real migration, physical click, or installed Host claim.
import AppKit
import Sparkle
import Darwin

enum Store { enum Kind { case thisMac, remote }; struct Backend { let kind: Kind }; static var active: Backend? = Backend(kind: .thisMac) }
enum WizardShared {
    static var legacyBootstrapNeeded = true
    static var osInstalled = true
    static let supportDir = URL(fileURLWithPath: CommandLine.arguments[1])
    static var osDir: URL { supportDir.appendingPathComponent("os") }
    static var statusFile: URL { supportDir.appendingPathComponent("host-status.json") }
    static let diskIdentity = "fixture-no-real-disk"
    static func probeReady(_ done: @escaping (Bool)->Void) { done(false) }
}
enum HostControl { static var isRunning = false; static var hasForeignRunner = false
    static func ensureRunning() { preconditionFailure("No Host launch in policy fixture") }
    static func send(_ command: String) { preconditionFailure("No Host IPC in policy fixture") }
}
struct WizardRelease: Codable {
    let schema: Int; let arch: String; let minimumPeer: Int; let hostProtocol: Int; let build: String; let releaseID: String; let guestPatch: String?
    static let peer = 1
    static func read(_ u: URL) throws -> WizardRelease { throw WizardUpdate.error("fixture must stop before release validation") }
    func validate(_ u: URL, verifyGuestFiles: Bool = true) throws { throw WizardUpdate.error("fixture") }
    func validateMetadata() throws { throw WizardUpdate.error("fixture") }
}
final class WizardDiskOwnership { static var acquired = 0
    func acquire() throws { Self.acquired += 1 }; func release() {}
}
enum WizardUpdate {
    static var dir: URL { WizardShared.supportDir.appendingPathComponent("updates") }
    static var journal: URL { dir.appendingPathComponent("transaction.json") }
    static var maintenanceJournal: URL { dir.appendingPathComponent("maintenance.json") }
    static var request: URL { dir.appendingPathComponent("request.json") }
    static var response: URL { dir.appendingPathComponent("response.json") }
    static func error(_ s: String)->NSError { NSError(domain: "fixture", code: 1, userInfo: [NSLocalizedDescriptionKey:s]) }
    static func sha256(_ p: URL) throws -> String { throw error("fixture stops at boot authentication") }
    static func write(_ o: [String:Any], _ p: URL) throws {
        precondition(p.lastPathComponent == "ui.json", "No transaction writes in policy fixture")
    }
    static func json(_ p: URL)->[String:Any] { [:] }
    static func run(_ path: String, _ args: [String]) throws { preconditionFailure("No subprocess in policy fixture") }
    static func idle(_ done: @escaping (String?)->Void) { done("Fixture does not certify guest idle") }
}
final class WizardGuestActivation {
    static let shared = WizardGuestActivation()
    var onProgress: (String)->Void = {_ in}; var onDone: (String?)->Void = {_ in}
    static func snapshotStoppedDisk() throws { preconditionFailure("Never snapshot a disk in UI policy fixture") }
    func activate() { preconditionFailure("Never migrate in UI policy fixture") }
    func recoverInterruptedActivation() { preconditionFailure("Never recover in UI policy fixture") }
}

@MainActor func exercise() {
    _ = NSApplication.shared
    NSApp.setActivationPolicy(.accessory)
    let u = WizardUpdater.shared
    var recording = true
    u.isRecording = { recording }
    precondition(u.admitLegacyBootstrap() && u.snapshot["phase"] as? String == "busy")
    precondition(WizardDiskOwnership.acquired == 0)
    print("LEGACY_REAL_UPDATER_CAPTURE_POLICY_REFUSED")
    recording = false; HostControl.isRunning = true
    precondition(u.admitLegacyBootstrap() && u.snapshot["phase"] as? String == "busy")
    HostControl.isRunning = false; HostControl.hasForeignRunner = true
    precondition(u.admitLegacyBootstrap() && u.snapshot["phase"] as? String == "busy")
    HostControl.hasForeignRunner = false
    print("LEGACY_RUNNING_AND_FOREIGN_HOST_POLICY_REFUSED")
    func alertAction(_ title: String, before: @escaping ()->Void = {}) {
        var ticks = 0
        let timer = Timer(timeInterval: 0.05, repeats: true) { timer in
            ticks += 1
            precondition(ticks < 100, "Bounded AppKit modal fixture")
            guard let window = NSApp.modalWindow, let root = window.contentView else { return }
            func buttons(_ v: NSView)->[NSButton] { (v as? NSButton).map { [$0] } ?? v.subviews.flatMap(buttons) }
            let found = buttons(root).filter { $0.title == title }
            precondition(found.count == 1, "Exact production alert button")
            before(); found[0].performClick(nil); timer.invalidate()
        }
        // runModal uses a nested AppKit mode; a default-mode timer can starve.
        RunLoop.main.add(timer, forMode: .modalPanel)
    }
    alertAction("Not now")
    precondition(u.admitLegacyBootstrap() && u.snapshot["phase"] as? String == "deferred")
    precondition(WizardDiskOwnership.acquired == 0)
    print("REAL_APPKIT_NOT_NOW_NO_DISK_OWNERSHIP")
    alertAction("Upgrade existing Wizard", before: { recording = true })
    precondition(u.admitLegacyBootstrap() && u.snapshot["phase"] as? String == "failed")
    precondition(WizardDiskOwnership.acquired == 0)
    precondition((u.snapshot["message"] as? String)?.contains("Activity changed while confirming") == true)
    print("REAL_APPKIT_CONFIRM_RACE_REVALIDATED_BEFORE_OWNERSHIP")
    recording = false
    alertAction("Upgrade existing Wizard")
    precondition(u.admitLegacyBootstrap() && u.snapshot["phase"] as? String == "failed")
    precondition(WizardDiskOwnership.acquired == 1)
    print("REAL_APPKIT_CONFIRM_REACHES_BOOT_AUTHENTICATION")
    var installed = false
    u.showReady { _ in installed = true }
    recording = true; u.updateAndRestart()
    precondition(u.snapshot["phase"] as? String == "busy" && !installed && !u.restartAuthorized)
    print("REAL_UPDATER_READY_CAPTURE_POLICY_REFUSED")
    print("FINAL307_APPKIT_POLICY_PASS_NOT_PHYSICAL_CAPTURE_OR_HOST")
}
// The generated main.swift invokes this function on the main thread.
