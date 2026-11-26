import Foundation

/// The maintenance lease a guest update asks for, tried again while the guest is still settling (try-wizard#191).
///
/// The Host asks a Mac-line guest for its maintenance lease (`POST /wizard/v1/maintenance`) seconds after the guest
/// first answers `/wizard/health`. Right after a boot, Runtipi is still starting and re-creating the runtime containers,
/// so the guest's lease helper can't read them yet: `docker ps/inspect/exec` fails and the guest refuses with
/// `runtime_control_failed` (or another "can't tell yet" code). That refusal says nothing about work: nothing was
/// stopped and nothing was authorised. On a fresh install the first refusal used to roll the bundled guest update
/// back for good, although the same lease was granted a second later.
///
/// So the guest update asks again, every `interval` seconds, for up to `window` seconds, while the refusal is a
/// "not ready yet" one. A real refusal is never retried and goes back to the caller at once, as before:
///   - work is running (an agent turn, a Hermes CLI/TUI session, a backend that is busy, an operation in flight),
///   - the lease belongs to someone else or this guest can't give one at all,
///   - anything that is not the Mac-line lease answering (the standard-install check, a token the Mac couldn't keep).
/// A refusal that says the guest kept a half-taken lease (`maintenance_recovery_required_cancel_with_same_token`) is
/// released with the same token first, which is what the guest asks for, then tried again.
enum WizardLeaseRetry {
    static let interval: TimeInterval = 5
    static let window: TimeInterval = 240
    /// Only refusals from the Mac-line lease route start this way (WizardUpdate.maintenance).
    static let leasePrefix = "Local maintenance deferred:"
    /// The guest's own words for work that is running (wizard-agent-service maintenanceReason) and the codes that never
    /// change by waiting. Any of these is final.
    static let final = [
        "is still working",                                  // agent_busy_finish_current_work_and_retry, backend_busy_or_unknown
        "Hermes session was started outside",                // unmanaged_session_busy_close_Hermes_sessions_and_retry
        "command-line or terminal session",                  // standalone_session_busy_close_CLI_or_TUI_and_retry
        "agent_busy", "session_busy", "backend_busy", "runtime_operation_in_flight",
        "maintenance_token_mismatch", "invalid_maintenance_token", "runtime_maintenance_barrier_unavailable",
        "managed_maintenance_unconfigured", "unknown_runtime_fail_closed", "owner_required", "access_required",
    ]
    static let recoveryRequired = "maintenance_recovery_required"

    enum Step: Equatable { case done, retry, releaseThenRetry }

    /// What to do with one answer of the lease: nil (granted) or the refusal the Host got.
    static func step(_ reason: String?, elapsed: TimeInterval, window: TimeInterval = window) -> Step {
        guard let reason, reason.hasPrefix(leasePrefix), elapsed < window else { return .done }
        if final.contains(where: { reason.contains($0) }) { return .done }
        return reason.contains(recoveryRequired) ? .releaseThenRetry : .retry
    }

    /// Ask for the lease until it is granted, refused for real, or the window ends; `done` gets the last answer.
    /// `lease` is one ask, `release` gives back a half-taken lease, `after` schedules the next ask.
    static func acquire(lease: @escaping (@escaping (String?) -> Void) -> Void,
                        release: @escaping (@escaping () -> Void) -> Void,
                        after: @escaping (TimeInterval, @escaping () -> Void) -> Void,
                        now: @escaping () -> Date = Date.init,
                        window: TimeInterval = window, interval: TimeInterval = interval,
                        log: @escaping (String) -> Void = { _ in },
                        done: @escaping (String?) -> Void) {
        let start = now()
        var tries = 0
        func ask() {
            tries += 1
            lease { reason in
                let elapsed = now().timeIntervalSince(start)
                switch step(reason, elapsed: elapsed, window: window) {
                case .done:
                    if tries > 1 { log(reason.map { "maintenance lease still refused after \(tries) tries: \($0)" } ?? "maintenance lease granted on try \(tries)") }
                    done(reason)
                case .retry:
                    log("maintenance lease not ready yet (try \(tries), \(Int(elapsed)) s): \(reason ?? "")")
                    after(interval, ask)
                case .releaseThenRetry:
                    log("maintenance lease half taken (try \(tries)); releasing it, then asking again")
                    release { after(interval, ask) }
                }
            }
        }
        ask()
    }
}
