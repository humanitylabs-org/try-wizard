import Foundation

/// Keep AppKit's main event loop running while Virtualization finishes shutdown.
/// Returning terminateLater from a main-dispatch notification callback nests
/// AppKit's termination loop inside that callback and can starve the very main
/// queue work needed by VZ shutdown. Cancel this request, stop asynchronously,
/// then request termination again only once the VM is actually stopped.
enum WizardHostTermination {
    enum Decision: Equatable { case terminate, cancel, stopThenRetry }

    static func decide(quitting: Bool, canTerminateWithoutStopping: Bool,
                       updateBusy: Bool) -> Decision {
        // An authenticated update marks quitting after its clean stop. A second
        // ordinary Quit while stopping must NOT bypass the live-VM guard.
        if quitting { return canTerminateWithoutStopping ? .terminate : .cancel }
        if updateBusy { return .cancel }
        if canTerminateWithoutStopping { return .terminate }
        return .stopThenRetry
    }
}
