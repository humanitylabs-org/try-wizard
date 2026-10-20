import AppKit
import Foundation

// Actual AppKit event-loop regression, with a simulated asynchronous VM stop.
// This does not instantiate a VM, open a user disk, record audio or alter TCC.
final class TerminationQA: NSObject, NSApplicationDelegate {
    var quitting = false
    var stopped = false
    var updateBusy = true
    var stopRequests = 0
    var repeatedQuitCancelled = false
    var busyQuitCancelled = false
    var policyAssertions = 0
    let legacy = CommandLine.arguments.contains("--legacy")
    let output = URL(fileURLWithPath: CommandLine.arguments[1])

    func applicationDidFinishLaunching(_ notification: Notification) {
        for quitting in [false, true] {
            for stopped in [false, true] {
                for busy in [false, true] {
                    let actual = WizardHostTermination.decide(quitting: quitting,
                        canTerminateWithoutStopping: stopped, updateBusy: busy)
                    let expected: WizardHostTermination.Decision = quitting
                        ? (stopped ? .terminate : .cancel)
                        : (busy ? .cancel : (stopped ? .terminate : .stopThenRetry))
                    precondition(actual == expected); policyAssertions += 1
                }
            }
        }
        // Match Host.command's main-dispatch notification entry, not a direct
        // pre-run call to shouldTerminate that misses the nested-runloop bug.
        DispatchQueue.main.async {
            NSApp.terminate(nil)
            self.busyQuitCancelled = !self.quitting && !self.stopped
            self.updateBusy = false
            NSApp.terminate(nil)
        }
    }

    func stop(_ completion: @escaping () -> Void) {
        stopRequests += 1
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
            let before = self.stopRequests
            NSApp.terminate(nil)
            self.repeatedQuitCancelled = !self.stopped && self.stopRequests == before
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            self.stopped = true
            completion()
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if legacy {
            if quitting { return .terminateNow }
            if updateBusy { return .terminateCancel }
            quitting = true
            if stopped { return .terminateNow }
            stop { NSApp.reply(toApplicationShouldTerminate: true) }
            return .terminateLater
        }
        switch WizardHostTermination.decide(quitting: quitting,
                    canTerminateWithoutStopping: stopped, updateBusy: updateBusy) {
        case .terminate: return .terminateNow
        case .cancel: return .terminateCancel
        case .stopThenRetry:
            quitting = true
            stop { NSApp.terminate(nil) }
            return .terminateCancel
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        let success = stopped && stopRequests == 1 && repeatedQuitCancelled && busyQuitCancelled
        let receipt: [String: Any] = ["pass": success, "actualAppKitEventLoop": true,
            "simulatedVM": true, "policyAssertions": policyAssertions,
            "stopRequests": stopRequests, "stopCallbackRan": stopped,
            "busyQuitCancelled": busyQuitCancelled,
            "repeatedQuitCancelledUntilStopped": repeatedQuitCancelled]
        try! JSONSerialization.data(withJSONObject: receipt, options: [.prettyPrinted, .sortedKeys]).write(to: output)
    }
}

let app = NSApplication.shared
let delegate = TerminationQA()
app.delegate = delegate
app.setActivationPolicy(.prohibited)
app.run()
