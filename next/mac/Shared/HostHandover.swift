import Foundation

/// After a Mac app update the new app must see a Host of its OWN build report healthy (try-wizard#127).
/// Updating from build 311 to 312 left the window on the logo with "New Host health not confirmed": the app only
/// waited 300 s for the new Host and never acted. This decides, one status read at a time, what the app does next:
/// ask an older Host that still owns this data folder to quit (a normal, graceful quit that stops WizardOS
/// cleanly; never a force kill and never touching data), launch the new Host when none runs, tell a new Host
/// whose WizardOS is stopped to start it, and say so in plain words with a working Retry when nothing has come
/// up after `stallSeconds`. Pure logic, so the fixtures in Tests/HostHandover drive it without a Mac or a VM.
struct WizardHostHandover {
    enum Step: Equatable {
        /// Nothing to do this tick; read the status again shortly.
        case wait
        /// The new Host runs WizardOS: check the front door answers before calling it healthy.
        case probe
        /// The new Host is up and there is no WizardOS to run yet: the update is complete.
        case activated
        /// The new Host is up but WizardOS is stopped: ask it to start.
        case startOS
        /// A Host of an older build still owns this data folder: ask that process to quit normally.
        case stopOldHost(Int32)
        /// No Host process at all: launch the new one.
        case launchHost
        /// Nothing healthy yet: show the plain recovery message (once) and keep trying.
        case stalled
        /// Out of time: show the plain recovery message and stop until the owner presses Retry.
        case gaveUp
    }

    /// The owner sees a plain message with Retry this soon if no new Host has come up.
    static let stallSeconds: TimeInterval = 30
    /// A new Host still booting WizardOS keeps being watched this long before the watch stops.
    static let bootSeconds: TimeInterval = 300
    /// Launching or starting is repeated at most this often, and a launch at most `maxLaunches` times.
    static let actionInterval: TimeInterval = 5
    static let maxLaunches = 3

    /// The one message the owner sees when the new Host did not come up. No paths, one action.
    static let troubleText = "WizardOS didn't restart after the update. Click Retry. If that doesn't help, quit Wizard from the menu bar and open it again. Your data is safe."

    let startedAt: Date
    private(set) var askedToQuit: Set<Int32> = []
    private(set) var launches = 0
    private(set) var lastLaunch: Date?
    private(set) var lastStart: Date?
    private(set) var stallShown = false
    /// True once this handover had to do anything beyond waiting (the window then reconnects when it ends well).
    private(set) var intervened = false

    init(startedAt: Date) { self.startedAt = startedAt }

    /// - Parameters:
    ///   - status: host-status.json as written by the Host.
    ///   - build: this app's build (CFBundleVersion); only a Host of this build counts as the new one.
    ///   - pidAlive: whether a process id is alive.
    ///   - isHostProcess: whether a live process id is a Wizard Host (bundle id), so a reused pid is ignored.
    ///   - anyHostRunning: whether any Wizard Host process runs at all.
    mutating func next(status: [String: Any], build: String, peer: Int, dataHome: String, now: Date,
                       pidAlive: (Int32) -> Bool, isHostProcess: (Int32) -> Bool, anyHostRunning: Bool) -> Step {
        let elapsed = now.timeIntervalSince(startedAt)
        let pid = (status["pid"] as? NSNumber)?.int32Value
        let alive = pid.map { $0 > 0 && pidAlive($0) } ?? false
        let ours = status["dataHome"] as? String == dataHome
        let statusBuild = status["build"] as? String ?? ""

        if ours, alive, statusBuild == build, (status["hostProtocol"] as? NSNumber)?.intValue == peer {
            switch status["state"] as? String {
            case "notInstalled": return .activated
            case "running": return .probe
            case "stopped":
                if lastStart.map({ now.timeIntervalSince($0) >= Self.actionInterval }) ?? true {
                    lastStart = now; intervened = true; return .startOS
                }
            case "error":
                // WizardOS itself failed to start: say so now rather than after the boot window.
                return fallback(elapsed, force: true)
            default: break // starting / stopping: give it the boot window
            }
            return elapsed > Self.bootSeconds ? .gaveUp : .wait
        }

        if ours, alive, let pid, statusBuild != build, isHostProcess(pid) {
            if !askedToQuit.contains(pid) { askedToQuit.insert(pid); intervened = true; return .stopOldHost(pid) }
            return fallback(elapsed)
        }

        if !anyHostRunning, launches < Self.maxLaunches,
           lastLaunch.map({ now.timeIntervalSince($0) >= Self.actionInterval }) ?? true {
            launches += 1; lastLaunch = now
            if launches > 1 { intervened = true }
            return .launchHost
        }
        return fallback(elapsed)
    }

    private mutating func fallback(_ elapsed: TimeInterval, force: Bool = false) -> Step {
        if elapsed > Self.bootSeconds { return .gaveUp }
        if !stallShown, force || elapsed > Self.stallSeconds { stallShown = true; intervened = true; return .stalled }
        return .wait
    }
}
