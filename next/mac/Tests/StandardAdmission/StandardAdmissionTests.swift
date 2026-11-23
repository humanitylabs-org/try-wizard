import XCTest
@testable import WizardStandardAdmission

/// try-wizard#154: on a standard-install guest (no /wizard/v1/maintenance route) the Host asks the guest what is
/// running before it stops WizardOS for a Wizard.app update. These are the guest's real answer shapes: `wam work`
/// (a list), `wam updates` (an object with waiting_for) and the Agent Service /wizard/health queue.
final class StandardAdmissionTests: XCTestCase {
    func d(_ s: String) -> Data { Data(s.utf8) }
    let quietStatus = "{\"installed\": \"0.3.240\", \"update_available\": false, \"waiting_for\": []}"
    func health(active: Int = 0, queued: Int = 0, liveness: Bool = true) -> Data {
        d("{\"status\":\"ok\",\"upstream_reachable\":true,\"queue\":{\"active\":\(active),\"queued\":\(queued),\"liveness_available\":\(liveness)}}")
    }

    func testQuietGuestIsAdmitted() {
        XCTAssertNil(WizardStandardAdmission.reason(work: d("[]"), status: d(quietStatus), health: health()))
    }

    func testOlderGuestWithoutWorkCommandStillAsksTheRest() {
        // wizard-ctl before #154 answers "unknown" to `work`; no answer at all is the same.
        XCTAssertNil(WizardStandardAdmission.reason(work: d("unknown\n"), status: d(quietStatus), health: health()))
        XCTAssertNil(WizardStandardAdmission.reason(work: nil, status: d(quietStatus), health: health()))
        // ...and a chat reply in progress still refuses, by name.
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("unknown\n"), status: d(quietStatus), health: health(active: 1)),
                       "Wizard is working on a chat reply — updates when it finishes")
        XCTAssertNotNil(WizardStandardAdmission.reason(work: nil, status: d(quietStatus), health: health(queued: 2)))
    }

    func testRunningWorkIsNamed() {
        let work = "[{\"kind\":\"agent\",\"name\":\"Replying in “Trip plans”\",\"source\":\"state\",\"stops_at\":\"hermes\"},"
            + "{\"kind\":\"agent\",\"name\":\"Scheduled job “Morning report”\",\"source\":\"cron\",\"stops_at\":\"hermes\"}]"
        XCTAssertEqual(WizardStandardAdmission.reason(work: d(work), status: d(quietStatus), health: health()),
                       "Wizard is working on a reply in “Trip plans” and scheduled job “Morning report” — updates when it finishes")
    }

    func testWaitingForFromAPendingOSUpdateCounts() {
        let st = "{\"update_available\": true, \"waiting_for\": [{\"kind\":\"agent\",\"name\":\"Hermes is working\",\"stops_at\":\"hermes\"}]}"
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("unknown"), status: d(st), health: health()),
                       "Wizard is working on an agent task — updates when it finishes")
    }

    func testDuplicateChatReplyNamedOnce() {
        let work = "[{\"kind\":\"agent\",\"name\":\"A chat reply\",\"source\":\"agent-service\",\"stops_at\":\"service\"}]"
        XCTAssertEqual(WizardStandardAdmission.reason(work: d(work), status: d(quietStatus), health: health(active: 1)),
                       "Wizard is working on a chat reply — updates when it finishes")
    }

    func testAnythingUnreadableRefuses() {
        let unknown = WizardStandardAdmission.unknownText
        // The App Manager didn't answer, or answered an error.
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("[]"), status: nil, health: health()), unknown)
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("[]"), status: d("{\"error\": \"the App Manager did not answer\"}"), health: health()), unknown)
        // The Agent Service queue can't be read or doesn't know its liveness: never read as idle.
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("[]"), status: d(quietStatus), health: nil), unknown)
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("[]"), status: d(quietStatus), health: health(liveness: false)), unknown)
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("[]"), status: d(quietStatus), health: d("{\"error\":\"not_found\"}")), unknown)
        // A WAM reader that failed (kind unknown) and a work command that errored.
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("[{\"kind\":\"unknown\",\"name\":\"Couldn't read cron\"}]"), status: d(quietStatus), health: health()), unknown)
        XCTAssertEqual(WizardStandardAdmission.reason(work: d("{\"error\":\"boom\"}"), status: d(quietStatus), health: health()), unknown)
    }

    func testLongListIsShort() {
        let names = ["Task “A”", "Task “B”", "Task “C”", "Task “D”", "Task “E”"]
        XCTAssertEqual(WizardStandardAdmission.busyText(names),
                       "Wizard is working on task “A”, task “B”, task “C” and 2 more — updates when it finishes")
    }
}
