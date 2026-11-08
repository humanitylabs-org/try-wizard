import Foundation
let root = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
enum WizardShared { static var logsDir: URL { root }; static var statusFile: URL { root.appendingPathComponent("status.json") } }
enum WizardUpdate { static func json(_ url: URL) -> [String:Any] { [:] } }
final class Probe {
 var entered = false; var failed: String? = nil
 var onProgress: (String)->Void = { _ in }
 func finish(_ text: String) { failed = text }
 func waitColdStarted(_ deadline: Date) { entered = true }
 func run(_ start: Date) { waitColdBoot(since: start) }
    private var waitingNoticeShown = false
    private func waitColdBoot(since start: Date) {
        let console = WizardShared.logsDir.appendingPathComponent("console.log")
        let attributes = try? FileManager.default.attributesOfItem(atPath: console.path)
        let written = (attributes?[.size] as? NSNumber)?.intValue ?? 0
        let modified = attributes?[.modificationDate] as? Date ?? .distantPast
        // The Host truncates the console before each boot. Both ordinary output
        // and cold verdicts must be newer than this activation's launch boundary;
        // a retained verdict is not evidence that the new VM has started.
        if written > 0 && modified >= start {
            waitingNoticeShown = false; waitColdStarted(Date().addingTimeInterval(150)); return
        }
        let status = WizardUpdate.json(WizardShared.statusFile)
        if status["state"] as? String == "error", (status["updatedAt"] as? Double ?? 0) >= start.timeIntervalSince1970 {
            finish(status["error"] as? String ?? "Wizard OS could not start; restoring the stopped disk"); return
        }
        let waited = Date().timeIntervalSince(start)
        guard waited < 900 else { finish("Wizard OS did not start within 15 minutes; restoring the stopped disk"); return }
        if waited > 3 && !waitingNoticeShown {
            waitingNoticeShown = true
            onProgress("Waiting for macOS to start Wizard's computer. If it asks whether Wizard may access a folder, click Allow.")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.waitColdBoot(since: start) }
    }

}
let console = root.appendingPathComponent("console.log")
let start = Date().addingTimeInterval(-200)
let delayed = Probe(); delayed.run(start)
precondition(!delayed.entered && delayed.failed == nil)
try "this boot: kernel started".write(to: console, atomically: true, encoding: .utf8)
let fresh = Probe(); fresh.run(start); precondition(fresh.entered)
try "previous boot WIZARD_COLD_FENCED".write(to: console, atomically: true, encoding: .utf8)
try FileManager.default.setAttributes([.modificationDate: start.addingTimeInterval(-60)], ofItemAtPath: console.path)
let stale = Probe(); stale.run(start)
print("DELAYED_BOOT_STAYS_WAITING_PASS")
print("FRESH_CONSOLE_STARTS_150S_BUDGET_PASS")
print("STALE_VERDICT_STARTS_150S_BUDGET=\(stale.entered)")
