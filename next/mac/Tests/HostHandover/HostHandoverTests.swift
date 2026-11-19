import XCTest
@testable import WizardHostHandover

/// try-wizard#127: updating the Mac app from build 311 to 312 left the window on the logo with
/// "New Host health not confirmed". These fixtures replay host-status.json as the new app sees it after an update.
final class HostHandoverTests: XCTestCase {
    let home = "/Users/owner/Library/Application Support/Wizard MVP"
    let t0 = Date(timeIntervalSince1970: 1_000_000)
    let oldPid: Int32 = 4242, newPid: Int32 = 5151

    func status(build: String, pid: Int32, state: String, home: String? = nil) -> [String: Any] {
        ["build": build, "pid": NSNumber(value: pid), "state": state, "hostProtocol": NSNumber(value: 1),
         "dataHome": home ?? self.home, "updatedAt": 0]
    }
    /// Steps the handover once per 0.5 s (as the app does) against a scripted world until it ends or time runs out.
    func run(_ h: inout WizardHostHandover, until seconds: TimeInterval,
             world: (TimeInterval, WizardHostHandover.Step?) -> (status: [String: Any], alive: Set<Int32>, hosts: Set<Int32>),
             stopAt: (WizardHostHandover.Step) -> Bool) -> [(TimeInterval, WizardHostHandover.Step)] {
        var steps: [(TimeInterval, WizardHostHandover.Step)] = []
        var last: WizardHostHandover.Step?
        var t: TimeInterval = 0
        while t <= seconds {
            let w = world(t, last)
            let step = h.next(status: w.status, build: "312", peer: 1, dataHome: home, now: t0.addingTimeInterval(t),
                              pidAlive: { w.alive.contains($0) }, isHostProcess: { w.hosts.contains($0) },
                              anyHostRunning: !w.hosts.isEmpty)
            if step != .wait { steps.append((t, step)) }
            last = step
            if stopAt(step) { break }
            t += 0.5
        }
        return steps
    }

    /// Acceptance a: an older build's Host is still alive when the new app starts. It is asked to quit (normally,
    /// once), the new Host is launched once it is gone, and the new build reaches healthy well inside 30 s.
    func testOldHostStillRunningIsReplacedAndNewBuildBecomesHealthy() {
        var h = WizardHostHandover(startedAt: t0)
        var oldQuitAt: TimeInterval?, launchedAt: TimeInterval?
        let steps = run(&h, until: 60, world: { t, last in
            if case .stopOldHost(let pid)? = last, oldQuitAt == nil { XCTAssertEqual(pid, self.oldPid); oldQuitAt = t }
            if last == .launchHost, launchedAt == nil { launchedAt = t }
            if let launchedAt, t >= launchedAt + 3 { return (self.status(build: "312", pid: self.newPid, state: "running"), [self.newPid], [self.newPid]) }
            if let oldQuitAt, t >= oldQuitAt + 4 { return (self.status(build: "311", pid: self.oldPid, state: "stopped"), [], []) }
            return (self.status(build: "311", pid: self.oldPid, state: "stopped"), [self.oldPid], [self.oldPid])
        }, stopAt: { $0 == .probe })
        XCTAssertEqual(steps.filter { if case .stopOldHost = $0.1 { return true }; return false }.count, 1, "asked once, never forced")
        XCTAssertEqual(steps.first?.1, .stopOldHost(oldPid))
        XCTAssertTrue(steps.contains { $0.1 == .launchHost })
        let probe = steps.first { $0.1 == .probe }
        XCTAssertNotNil(probe); XCTAssertLessThan(probe!.0, 30)
        XCTAssertFalse(steps.contains { $0.1 == .stalled || $0.1 == .gaveUp })
        XCTAssertTrue(h.intervened, "the window reconnects after a replaced Host")
    }

    /// Acceptance a (other half): the old Host never goes away. The owner sees the plain recovery message with
    /// Retry within 30 s, the old Host is asked only once, and nothing is ever force-stopped.
    func testOldHostThatWontQuitShowsRecoveryWithin30Seconds() {
        var h = WizardHostHandover(startedAt: t0)
        let steps = run(&h, until: 40, world: { _, _ in
            (self.status(build: "311", pid: self.oldPid, state: "running"), [self.oldPid], [self.oldPid])
        }, stopAt: { _ in false })
        XCTAssertEqual(steps.map { $0.1 }, [.stopOldHost(oldPid), .stalled])
        XCTAssertLessThanOrEqual(steps[1].0, 31)
    }

    /// Acceptance b: no Host starts at all. Launch is tried a few times, then the plain recovery message shows
    /// within 30 s; Retry (a fresh handover) launches again.
    func testNoHostEverStartsShowsRecoveryAndRetryLaunchesAgain() {
        var h = WizardHostHandover(startedAt: t0)
        let stale = status(build: "311", pid: oldPid, state: "stopped")
        var steps = run(&h, until: 40, world: { _, _ in (stale, [], []) }, stopAt: { _ in false })
        XCTAssertEqual(steps.filter { $0.1 == .launchHost }.count, WizardHostHandover.maxLaunches)
        let stall = steps.first { $0.1 == .stalled }
        XCTAssertNotNil(stall); XCTAssertLessThanOrEqual(stall!.0, 31)
        XCTAssertEqual(steps.filter { $0.1 == .stalled }.count, 1, "the message is shown once, not flashed")
        // Retry: a new handover starts from scratch and launches straight away.
        h = WizardHostHandover(startedAt: t0.addingTimeInterval(100))
        let step = h.next(status: stale, build: "312", peer: 1, dataHome: home, now: t0.addingTimeInterval(100),
                          pidAlive: { _ in false }, isHostProcess: { _ in false }, anyHostRunning: false)
        XCTAssertEqual(step, .launchHost)
    }

    /// The watch ends: after the boot window it gives up (Retry starts it again) rather than polling forever.
    func testGivesUpAfterBootWindow() {
        var h = WizardHostHandover(startedAt: t0)
        let steps = run(&h, until: 400, world: { _, _ in (self.status(build: "311", pid: 1, state: "stopped"), [], []) },
                        stopAt: { $0 == .gaveUp })
        XCTAssertEqual(steps.last?.1, .gaveUp)
        XCTAssertGreaterThan(steps.last!.0, WizardHostHandover.bootSeconds)
    }

    /// The new Host came up but WizardOS is stopped (its own start was missed): it is told to start, then healthy.
    func testNewHostWithStoppedOSIsToldToStart() {
        var h = WizardHostHandover(startedAt: t0)
        var started = false
        let steps = run(&h, until: 20, world: { _, last in
            if last == .startOS { started = true }
            return (self.status(build: "312", pid: self.newPid, state: started ? "running" : "stopped"), [self.newPid], [self.newPid])
        }, stopAt: { $0 == .probe })
        XCTAssertEqual(steps.map { $0.1 }, [.startOS, .probe])
    }

    /// Acceptance c: an ordinary managed update (old Host stopped cleanly before install) still goes straight
    /// through: one launch, then the new build is healthy, and the window is left alone.
    func testOrdinaryManagedUpdateStillCompletes() {
        var h = WizardHostHandover(startedAt: t0)
        var launched = false
        let steps = run(&h, until: 20, world: { t, last in
            if last == .launchHost { launched = true }
            guard launched, t > 2 else { return (self.status(build: "311", pid: self.oldPid, state: "stopped"), [], []) }
            return (self.status(build: "312", pid: self.newPid, state: t > 5 ? "running" : "starting"), [self.newPid], [self.newPid])
        }, stopAt: { $0 == .probe })
        XCTAssertEqual(steps.map { $0.1 }, [.launchHost, .probe])
        XCTAssertFalse(h.intervened)
        // No WizardOS installed yet: the new Host alone completes the update.
        var fresh = WizardHostHandover(startedAt: t0)
        XCTAssertEqual(fresh.next(status: status(build: "312", pid: newPid, state: "notInstalled"), build: "312", peer: 1,
                                  dataHome: home, now: t0, pidAlive: { _ in true }, isHostProcess: { _ in true },
                                  anyHostRunning: true), .activated)
    }

    /// Never touch what isn't ours: another data folder's Host, or a reused pid that is not a Wizard Host.
    func testIgnoresOtherDataHomesAndReusedPids() {
        var h = WizardHostHandover(startedAt: t0)
        let other = status(build: "311", pid: oldPid, state: "running", home: "/Users/owner/Other")
        XCTAssertEqual(h.next(status: other, build: "312", peer: 1, dataHome: home, now: t0, pidAlive: { _ in true },
                              isHostProcess: { _ in true }, anyHostRunning: true), .wait)
        var r = WizardHostHandover(startedAt: t0)
        XCTAssertEqual(r.next(status: status(build: "311", pid: oldPid, state: "running"), build: "312", peer: 1,
                              dataHome: home, now: t0, pidAlive: { _ in true }, isHostProcess: { _ in false },
                              anyHostRunning: false), .launchHost)
    }

    /// The new Host's WizardOS failed: say so at once in plain words.
    func testNewHostErrorShowsRecoveryAtOnce() {
        var h = WizardHostHandover(startedAt: t0)
        XCTAssertEqual(h.next(status: status(build: "312", pid: newPid, state: "error"), build: "312", peer: 1,
                              dataHome: home, now: t0.addingTimeInterval(1), pidAlive: { _ in true },
                              isHostProcess: { _ in true }, anyHostRunning: true), .stalled)
    }

    func testRecoveryTextIsPlain() {
        let text = WizardHostHandover.troubleText
        for bad in ["/", ".app", "Host", "health", "updates"] { XCTAssertFalse(text.contains(bad), bad) }
        XCTAssertTrue(text.contains("Retry"))
    }
}
