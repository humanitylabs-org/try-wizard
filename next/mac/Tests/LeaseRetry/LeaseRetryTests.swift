import XCTest
@testable import WizardLeaseRetry

/// try-wizard#191: a fresh Mac's bundled guest update asked for the maintenance lease seconds after the guest booted,
/// got `runtime_control_failed` once, and rolled back for good. The refusal texts here are the guest's own
/// (wizard-agent-service maintenanceReason, wrapped by WizardUpdate.maintenance).
final class LeaseRetryTests: XCTestCase {
    static func deferred(_ code: String) -> String {
        "Local maintenance deferred: The local runtime could not safely enter maintenance. No update was authorized. \(code)"
    }
    let notReady = deferred("runtime_control_failed")
    let busy = "Local maintenance deferred: A local agent is still working. Let it finish, then retry the update."

    /// Runs acquire() on a fake clock: `after` moves the clock and runs the next ask at once.
    final class Run {
        var clock = Date(timeIntervalSince1970: 1_000)
        var asks = 0, releases = 0
        var waits: [TimeInterval] = []
        var result: String?? = .none
        var logs: [String] = []
        init(answers: @escaping (Int) -> String?, window: TimeInterval = WizardLeaseRetry.window) {
            WizardLeaseRetry.acquire(
                lease: { [unowned self] answer in self.asks += 1; answer(answers(self.asks)) },
                release: { [unowned self] next in self.releases += 1; next() },
                after: { [unowned self] delay, next in self.waits.append(delay); self.clock += delay; next() },
                now: { [unowned self] in self.clock },
                window: window,
                log: { [unowned self] in self.logs.append($0) },
                done: { [unowned self] in self.result = .some($0) })
        }
    }

    func testLeaseThatFailsOnceThenSucceedsIsGranted() {
        let run = Run(answers: { $0 == 1 ? self.notReady : nil })
        XCTAssertEqual(run.asks, 2)
        XCTAssertEqual(run.result, .some(nil), "the second answer (granted) reaches the update")
        XCTAssertEqual(run.waits, [WizardLeaseRetry.interval])
        XCTAssertTrue(run.logs.contains("maintenance lease granted on try 2"))
    }

    func testFirstGrantNeedsNoRetry() {
        let run = Run(answers: { _ in nil })
        XCTAssertEqual(run.asks, 1)
        XCTAssertEqual(run.result, .some(nil))
        XCTAssertTrue(run.waits.isEmpty)
    }

    func testOtherNotReadyRefusalsAreRetried() {
        for code in ["runtime_inventory_unknown", "maintenance_runtime_unknown", "runtime_unreachable", "admission_in_flight",
                     "gateway_drain_ack_unknown", "runtime_did_not_retire"] {
            let run = Run(answers: { $0 < 3 ? Self.deferred(code) : nil })
            XCTAssertEqual(run.asks, 3, code)
            XCTAssertEqual(run.result, .some(nil), code)
        }
        // No answer at all (timeout, connection refused while the guest settles).
        let silent = Run(answers: { $0 == 1 ? "Local maintenance deferred: cannot verify all local runtimes" : nil })
        XCTAssertEqual(silent.result, .some(nil))
    }

    func testRealRefusalStillRollsBackAtOnce() {
        let refusals = [busy,
                        "Local maintenance deferred: A Hermes session was started outside managed launching. Close that session normally, then retry. It has not been interrupted.",
                        "Local maintenance deferred: A Hermes command-line or terminal session is still open. Finish and close it normally, then retry. It has not been interrupted.",
                        Self.deferred("runtime_operation_in_flight"), Self.deferred("maintenance_token_mismatch"),
                        Self.deferred("runtime_maintenance_barrier_unavailable"), Self.deferred("unknown_runtime_fail_closed")]
        for refusal in refusals {
            let run = Run(answers: { _ in refusal })
            XCTAssertEqual(run.asks, 1, refusal)
            XCTAssertEqual(run.result, .some(refusal), refusal)
        }
    }

    func testNonLeaseAnswersAreNotRetried() {
        // The standard-install check (onMissing) and the Mac's own failures have no lease prefix.
        for reason in ["Wizard is working on a chat reply — updates when it finishes",
                       "Wizard couldn't check what is running on this Mac — it updates when it can",
                       "Cannot retain local maintenance recovery token"] {
            let run = Run(answers: { _ in reason })
            XCTAssertEqual(run.asks, 1, reason)
            XCTAssertEqual(run.result, .some(reason), reason)
        }
    }

    func testRetriesStopAtTheWindowWithTheLastRefusal() {
        let run = Run(answers: { _ in self.notReady })
        XCTAssertEqual(run.result, .some(notReady))
        XCTAssertEqual(run.asks, Int(WizardLeaseRetry.window / WizardLeaseRetry.interval) + 1)
        XCTAssertLessThanOrEqual(run.waits.reduce(0, +), WizardLeaseRetry.window)
        XCTAssertTrue(run.logs.last?.hasPrefix("maintenance lease still refused after") == true)
    }

    func testHalfTakenLeaseIsReleasedBeforeAskingAgain() {
        let run = Run(answers: { $0 == 1 ? Self.deferred("maintenance_recovery_required_cancel_with_same_token") : nil })
        XCTAssertEqual(run.releases, 1)
        XCTAssertEqual(run.asks, 2)
        XCTAssertEqual(run.result, .some(nil))
    }

    func testStep() {
        XCTAssertEqual(WizardLeaseRetry.step(nil, elapsed: 0), .done)
        XCTAssertEqual(WizardLeaseRetry.step(notReady, elapsed: 0), .retry)
        XCTAssertEqual(WizardLeaseRetry.step(notReady, elapsed: WizardLeaseRetry.window), .done)
        XCTAssertEqual(WizardLeaseRetry.step(busy, elapsed: 0), .done)
    }
}
