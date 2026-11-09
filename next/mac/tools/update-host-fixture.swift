// Disposable QA Host protocol fixture. No VM, disk or production Host is opened.
import AppKit
let args = CommandLine.arguments
 guard let at = args.firstIndex(of: "--wizard-data-home"), args.count > at + 1 else { fatalError("Missing isolated data home") }
let home = URL(fileURLWithPath: args[at + 1])
let updates = home.appendingPathComponent("updates")
func json(_ url: URL) -> [String: Any] {
    ((try? Data(contentsOf: url)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }) ?? [:]
}
func write(_ object: [String: Any], _ url: URL) {
    try! FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try! JSONSerialization.data(withJSONObject: object).write(to: url, options: .atomic)
}
write(["hostProtocol": 1], home.appendingPathComponent("host-status.json"))
let token = DistributedNotificationCenter.default().addObserver(forName: Notification.Name("org.humanitylabs.wizard.mvp.host.command"), object: nil, queue: .main) { notification in
    if notification.object as? String == "prepare-update" {
        let request = json(updates.appendingPathComponent("host-request.json"))
        guard let nonce = request["nonce"] as? String else { return }
        // Leave enough time to exercise Quit during the stopping window.
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            write(["nonce": nonce, "state": "stopped"], updates.appendingPathComponent("host-response.json"))
            NSApp.terminate(nil)
        }
    } else if notification.object as? String == "quit" { NSApp.terminate(nil) }
}
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
app.run()
