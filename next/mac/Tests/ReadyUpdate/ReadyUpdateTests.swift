import XCTest
@testable import WizardReadyUpdate

/// try-wizard#128: a ready Wizard for Mac update can't wait forever.
final class ReadyUpdateTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_800_000_000)
    func at(hours: Double) -> Date { t0.addingTimeInterval(hours * 3600) }

    func testLaterHidesUntilTomorrowThenShowsOnce() {
        var r = WizardReadyUpdate.ready(nil, build: "326", critical: false, now: t0)
        r = WizardReadyUpdate.later(r, now: t0)
        XCTAssertTrue(WizardReadyUpdate.staysHidden(r, now: at(hours: 1)))
        XCTAssertFalse(WizardReadyUpdate.showAgain(r, now: at(hours: 23.9), barHidden: true))
        XCTAssertTrue(WizardReadyUpdate.showAgain(r, now: at(hours: 24), barHidden: true))
        // Shown once: the next checks that day don't show it again.
        r = WizardReadyUpdate.shown(r)
        XCTAssertFalse(WizardReadyUpdate.showAgain(r, now: at(hours: 25), barHidden: true))
        XCTAssertFalse(WizardReadyUpdate.staysHidden(r, now: at(hours: 25)))
        // Later again: another day.
        r = WizardReadyUpdate.later(r, now: at(hours: 25))
        XCTAssertFalse(WizardReadyUpdate.showAgain(r, now: at(hours: 48), barHidden: true))
        XCTAssertTrue(WizardReadyUpdate.showAgain(r, now: at(hours: 49), barHidden: true))
        // A bar that is already showing isn't shown again.
        XCTAssertFalse(WizardReadyUpdate.showAgain(r, now: at(hours: 49), barHidden: false))
    }

    func testOfferOnQuitAfterThreeDaysOnly() {
        let r = WizardReadyUpdate.ready(nil, build: "326", critical: false, now: t0)
        XCTAssertEqual(WizardReadyUpdate.offerOnQuitAfter, 3 * 24 * 3600)
        XCTAssertFalse(WizardReadyUpdate.offerOnQuit(r, readyBuild: "326", now: at(hours: 71.9)))
        XCTAssertTrue(WizardReadyUpdate.offerOnQuit(r, readyBuild: "326", now: at(hours: 72)))
        XCTAssertFalse(WizardReadyUpdate.offerOnQuit(nil, readyBuild: "326", now: at(hours: 100)))
        // An old record for another build never counts.
        XCTAssertFalse(WizardReadyUpdate.offerOnQuit(r, readyBuild: "327", now: at(hours: 100)))
        XCTAssertFalse(WizardReadyUpdate.offerOnQuit(r, readyBuild: "", now: at(hours: 100)))
    }

    func testReadySinceSurvivesRelaunchAndResetsForANewerBuild() {
        let first = WizardReadyUpdate.ready(nil, build: "326", critical: false, now: t0)
        // Saved and read back (a relaunch), the same build ready again two days later keeps its time.
        let stored = WizardReadyUpdate.Record.read(first.json)
        XCTAssertEqual(stored, first)
        let again = WizardReadyUpdate.ready(stored, build: "326", critical: false, now: at(hours: 48))
        XCTAssertEqual(again.readySince, t0.timeIntervalSince1970)
        XCTAssertTrue(WizardReadyUpdate.offerOnQuit(again, readyBuild: "326", now: at(hours: 73)))
        // A newer build replaces it: the clock starts over and an old Later is gone.
        let later = WizardReadyUpdate.later(again, now: at(hours: 48))
        let newer = WizardReadyUpdate.ready(later, build: "327", critical: false, now: at(hours: 50))
        XCTAssertEqual(newer.readySince, at(hours: 50).timeIntervalSince1970)
        XCTAssertNil(newer.laterUntil)
        XCTAssertFalse(WizardReadyUpdate.offerOnQuit(newer, readyBuild: "327", now: at(hours: 73)))
    }

    func testCriticalHasNoLater() {
        var r = WizardReadyUpdate.ready(nil, build: "326", critical: true, now: t0)
        r = WizardReadyUpdate.later(r, now: t0)
        XCTAssertNil(r.laterUntil)
        XCTAssertFalse(WizardReadyUpdate.staysHidden(r, now: at(hours: 1)))
        for phase in ["available", "downloading", "verifying", "ready", "busy", "stopping"] {
            XCTAssertFalse(WizardReadyUpdate.showsLater(critical: true, phase: phase), phase)
            XCTAssertTrue(WizardReadyUpdate.showsLater(critical: false, phase: phase), phase)
        }
        // Good news and failures keep a way to close the bar.
        XCTAssertTrue(WizardReadyUpdate.showsLater(critical: true, phase: "installed"))
        XCTAssertTrue(WizardReadyUpdate.showsLater(critical: true, phase: "failed"))
        // A release that turns critical drops a Later the owner chose before.
        let plain = WizardReadyUpdate.later(WizardReadyUpdate.ready(nil, build: "326", critical: false, now: t0), now: t0)
        XCTAssertNil(WizardReadyUpdate.ready(plain, build: "326", critical: true, now: at(hours: 1)).laterUntil)
    }

    func testRecordReadsWhatIsStored() {
        XCTAssertNil(WizardReadyUpdate.Record.read([:]))
        XCTAssertNil(WizardReadyUpdate.Record.read(["build": "", "readySince": 1.0]))
        let r = WizardReadyUpdate.Record.read(["build": "326", "readySince": 1_800_000_000, "laterUntil": 1_800_086_400])
        XCTAssertEqual(r?.readySince, 1_800_000_000)
        XCTAssertEqual(r?.laterUntil, 1_800_086_400)
        XCTAssertEqual(r?.critical, false)
    }

    func testSheetWords() {
        XCTAssertEqual(WizardReadyUpdate.quitTitle("0.8.15"), "Wizard for Mac 0.8.15 is ready. Install it while quitting?")
        XCTAssertEqual(WizardReadyUpdate.cannotText("Recording or agent work is active"),
                       "Recording or agent work is active. Wizard quits without updating and offers it again next time.")
        XCTAssertEqual(WizardReadyUpdate.cannotText("Stopping safely…"),
                       "Stopping safely… Wizard quits without updating and offers it again next time.")
    }
}
