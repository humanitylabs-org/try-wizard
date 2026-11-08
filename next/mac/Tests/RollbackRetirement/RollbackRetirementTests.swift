import XCTest
@testable import WizardRollbackRetirement

/// Issue #31: previous-disk.img must go after a confirmed update, and must stay in every other case.
final class RollbackRetirementTests: XCTestCase {
    let home = "/test/Wizard MVP"
    let now = Date(timeIntervalSince1970: 2_000_000_000)
    var dayAgo: Date { now.addingTimeInterval(-WizardRollbackRetirement.grace - 60) }

    func journal(_ phase: String, kind: String? = nil, disk: String = "1:42") -> [String: Any] {
        var j: [String: Any] = ["phase": phase, "dataHome": home, "diskIdentity": disk, "nonce": "n"]
        if let kind { j["kind"] = kind }
        return j
    }

    func verdict(_ j: [String: Any], disk: String? = "1:42", legacy: [String: Any] = [:],
                 at: Date? = nil, running: Bool = true) -> WizardRollbackRetirement.Verdict {
        WizardRollbackRetirement.verdict(journal: j, dataHome: home, diskIdentity: disk, legacyComplete: legacy,
                                         activatedAt: at ?? dayAgo, runningNormally: running, now: now)
    }

    func testRetiresAfterConfirmedActivation() {
        XCTAssertEqual(verdict(journal("guest-activated")), .retire)
    }

    func testRetiresLegacyColdOnlyWithMatchingCompletionReceipt() {
        let j = journal("guest-activated", kind: "legacy-cold")
        XCTAssertEqual(verdict(j, legacy: ["diskIdentity": "1:42", "releaseID": "r"]), .retire)
        if case .keep = verdict(j, legacy: [:]) {} else { XCTFail("missing legacy-complete.json must keep the clone") }
        if case .keep = verdict(j, legacy: ["diskIdentity": "1:7"]) {} else { XCTFail("stale receipt must keep the clone") }
    }

    func testKeepsDuringAndAfterAnyOtherPhase() {
        for phase in ["prepared", "installing", "guest-activating", "guest-rolled-back", "install-failed", "native-activated", ""] {
            if case .keep = verdict(journal(phase)) {} else { XCTFail("phase \(phase) must keep the clone") }
        }
    }

    func testKeepsWhenLiveDiskIsNotTheActivatedDisk() {
        if case .keep = verdict(journal("guest-activated"), disk: "1:99") {} else { XCTFail("replaced disk") }
        if case .keep = verdict(journal("guest-activated"), disk: nil) {} else { XCTFail("missing disk") }
    }

    func testKeepsForAnotherDataHome() {
        var j = journal("guest-activated"); j["dataHome"] = "/other"
        if case .keep = verdict(j) {} else { XCTFail("other data home") }
    }

    func testWaitsOutTheGracePeriod() {
        let hourAgo = now.addingTimeInterval(-3600)
        XCTAssertEqual(verdict(journal("guest-activated"), at: hourAgo), .waitForGrace(WizardRollbackRetirement.grace - 3600))
        // A clock that moved backwards waits the whole grace period, never less.
        XCTAssertEqual(verdict(journal("guest-activated"), at: now.addingTimeInterval(600)), .waitForGrace(WizardRollbackRetirement.grace))
        if case .keep = WizardRollbackRetirement.verdict(journal: journal("guest-activated"), dataHome: home, diskIdentity: "1:42",
                                                         legacyComplete: [:], activatedAt: nil, runningNormally: true, now: now) {} else {
            XCTFail("unknown activation time must keep the clone")
        }
    }

    func testWaitsUntilWizardRunsNormally() {
        XCTAssertEqual(verdict(journal("guest-activated"), running: false), .waitForRunning)
    }
}
