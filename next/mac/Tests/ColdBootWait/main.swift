import Foundation

let root = URL(fileURLWithPath: CommandLine.arguments[1])
let expectStaleBypass = CommandLine.arguments[2] == "true"
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
enum WizardShared {
    static var logsDir: URL { root }
    static var statusFile: URL { root.appendingPathComponent("status.json") }
}
enum WizardUpdate {
    static func json(_ url: URL) -> [String: Any] {
        (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any] ?? [:]
    }
}
// Capture, rather than accelerate or run, the production one-second retry.
// Tests explicitly advance the file/status inputs and invoke the saved callback.
enum DispatchQueue {
    static let main = Scheduler()
    final class Scheduler {
        var pending: [() -> Void] = []
        func asyncAfter(deadline: DispatchTime, execute: @escaping () -> Void) { pending.append(execute) }
    }
}
final class Probe {
    var deadline: Date?
    var failed: String?
    var notices: [String] = []
    lazy var onProgress: (String) -> Void = { self.notices.append($0) }
    func finish(_ text: String) { failed = text }
    func waitColdStarted(_ deadline: Date) { self.deadline = deadline }
    func run(_ start: Date) { waitColdBoot(since: start) }
// PRODUCTION_WAIT
}
let console = root.appendingPathComponent("console.log")
func write(_ text: String, modified: Date) throws {
    try text.write(to: console, atomically: true, encoding: .utf8)
    try FileManager.default.setAttributes([.modificationDate: modified], ofItemAtPath: console.path)
}
func status(_ state: String, updated: Date) throws {
    try JSONSerialization.data(withJSONObject: ["state": state, "updatedAt": updated.timeIntervalSince1970,
                                               "error": "folder access denied"]).write(to: WizardShared.statusFile)
}
func reset() {
    try? FileManager.default.removeItem(at: console)
    try? FileManager.default.removeItem(at: WizardShared.statusFile)
    DispatchQueue.main.pending.removeAll()
}
func isWaiting(_ probe: Probe) -> Bool { probe.deadline == nil && probe.failed == nil }
let start = Date().addingTimeInterval(-200) // more than the 150-second fence budget
var bypass = false
for verdict in ["WIZARD_COLD_FENCED", "WIZARD_COLD_FAILED"] {
    reset()
    try write("previous boot \(verdict)", modified: start.addingTimeInterval(-60))
    let delayed = Probe(); delayed.run(start)
    bypass = bypass || delayed.deadline != nil
    precondition((delayed.deadline != nil) == expectStaleBypass, "stale verdict must not start the new boot budget")
    if !expectStaleBypass {
        precondition(isWaiting(delayed) && delayed.notices.count == 1)
        precondition(delayed.notices[0].contains("click Allow"))
        precondition(DispatchQueue.main.pending.count == 1)
        // Repeat while permission is pending; no fence budget or repeated notice.
        DispatchQueue.main.pending.removeFirst()()
        precondition(isWaiting(delayed) && delayed.notices.count == 1)
        // Host truncates before VM output. An empty new console is not a boot.
        try write("", modified: Date())
        DispatchQueue.main.pending.removeFirst()()
        precondition(isWaiting(delayed))
        // New boot begins only after output; it gets a full 150 seconds now.
        try write("this boot: kernel started", modified: Date())
        DispatchQueue.main.pending.removeFirst()()
        precondition(delayed.deadline!.timeIntervalSinceNow > 149 && delayed.deadline!.timeIntervalSinceNow <= 150)
        precondition(DispatchQueue.main.pending.isEmpty)
    }
}
print("STALE_VERDICT_STARTS_150S_BUDGET=\(bypass)")
for text in ["this boot: kernel started", "WIZARD_COLD_FENCED", "WIZARD_COLD_FAILED"] {
    reset(); try write(text, modified: Date())
    let fresh = Probe(); fresh.run(start)
    precondition(fresh.deadline != nil && fresh.failed == nil)
}
print("FRESH_CONSOLE_AND_BOTH_VERDICTS_START_150S_BUDGET_PASS")
for empty in [false, true] {
    reset()
    if empty { try write("", modified: Date()) }
    let delayed = Probe(); delayed.run(start)
    precondition(isWaiting(delayed))
}
print("DELAYED_BOOT_STAYS_WAITING_PASS")
reset(); try status("error", updated: start.addingTimeInterval(-1))
let oldError = Probe(); oldError.run(start); precondition(isWaiting(oldError))
try status("error", updated: Date())
let denial = Probe(); denial.run(start); precondition(denial.failed == "folder access denied" && denial.deadline == nil)
print("CURRENT_HOST_ERROR_FAILS_PROMPTLY_OLD_ERROR_IGNORED_PASS")
reset()
let timedOut = Probe(); timedOut.run(Date().addingTimeInterval(-901))
precondition(timedOut.failed?.contains("15 minutes") == true && timedOut.deadline == nil)
print("PREBOOT_15_MINUTE_BOUND_PASS")
if !expectStaleBypass { print("DELAYED_PERMISSION_THEN_FRESH_BOOT_FULL_BUDGET_PASS") }
print("COLD_BOOT_WAIT_REGRESSIONS_PASS")
