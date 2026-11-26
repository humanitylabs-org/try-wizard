import XCTest
@testable import WizardAppUpdateStatus

/// try-wizard#126: the Mac app's own update state for the page, and releases that need a new download.
final class AppUpdateStatusTests: XCTestCase {
    typealias S = WizardAppUpdateStatus

    func testBarStatesMapOntoThePagePhases() {
        XCTAssertEqual(S.phase("idle", ready: false, manual: false), "idle")
        XCTAssertEqual(S.phase("checking", ready: false, manual: false), "checking")
        XCTAssertEqual(S.phase("current", ready: false, manual: false), "current")
        XCTAssertEqual(S.phase("installed", ready: false, manual: false), "current")
        XCTAssertEqual(S.phase("available", ready: false, manual: false), "downloading")
        XCTAssertEqual(S.phase("downloading", ready: false, manual: false), "downloading")
        XCTAssertEqual(S.phase("verifying", ready: false, manual: false), "verifying")
        XCTAssertEqual(S.phase("ready", ready: true, manual: false), "ready")
        XCTAssertEqual(S.phase("busy", ready: true, manual: false), "ready")      // waiting for a recording / work
        XCTAssertEqual(S.phase("busy", ready: false, manual: false), "idle")
        XCTAssertEqual(S.phase("stopping", ready: true, manual: false), "installing")
        XCTAssertEqual(S.phase("installing", ready: false, manual: false), "installing")
        XCTAssertEqual(S.phase("manual", ready: false, manual: true), "manual")
        XCTAssertEqual(S.phase("failed", ready: false, manual: false), "failed")
        XCTAssertEqual(S.phase("host-recovery", ready: false, manual: false), "failed")
        // A remembered new-download release stays the answer after a check finds nothing newer to install.
        XCTAssertEqual(S.phase("current", ready: false, manual: true), "manual")
        XCTAssertEqual(S.phase("idle", ready: false, manual: true), "manual")
        for state in ["idle", "checking", "current", "available", "downloading", "verifying", "ready", "busy", "stopping",
                      "installing", "manual", "failed", "host-recovery", "guest-pending", "guest-activating", "unknown"] {
            XCTAssertTrue(S.phases.contains(S.phase(state, ready: false, manual: false)), state)
        }
    }

    func testOnlyAiwizardsDownloadPagesOpen() {
        XCTAssertTrue(S.allowsDownload("https://www.aiwizards.com/downloads"))
        XCTAssertTrue(S.allowsDownload("https://downloads.aiwizards.com/mac/"))
        XCTAssertTrue(S.allowsDownload("https://DOWNLOADS.aiwizards.com/mac/330/Wizard-0.9.0.dmg"))
        for bad in [nil, "", "http://www.aiwizards.com/downloads", "https://aiwizards.com.evil.example/",
                    "https://evil.example/?u=https://www.aiwizards.com/", "https://www.aiwizards.com@evil.example/",
                    "https://user:pw@www.aiwizards.com/", "https://www.aiwizards.com:8443/", "file:///etc/passwd",
                    "javascript:alert(1)", "https://aiwizards.com/", "https://evil.aiwizards.com/"] {
            XCTAssertFalse(S.allowsDownload(bad), bad ?? "nil")
        }
        XCTAssertEqual(S.manualURL(link: "https://downloads.aiwizards.com/mac/"), "https://downloads.aiwizards.com/mac/")
        XCTAssertEqual(S.manualURL(link: nil), S.defaultDownloadURL)
        XCTAssertEqual(S.manualURL(link: "https://evil.example/wizard.dmg"), S.defaultDownloadURL)
    }

    func testTheManualRecordLastsUntilTheInstalledBuildReachesIt() {
        let stored = S.ManualRecord(version: "0.9.0", build: "330", url: "https://www.aiwizards.com/downloads").json
        XCTAssertEqual(S.ManualRecord.read(stored, installedBuild: "325"),
                       S.ManualRecord(version: "0.9.0", build: "330", url: "https://www.aiwizards.com/downloads"))
        XCTAssertNil(S.ManualRecord.read(stored, installedBuild: "330"))
        XCTAssertNil(S.ManualRecord.read(stored, installedBuild: "1000"))   // numeric, not text, order
        XCTAssertNotNil(S.ManualRecord.read(stored, installedBuild: "99"))
        var foreign = stored; foreign["url"] = "https://evil.example/"
        XCTAssertNil(S.ManualRecord.read(foreign, installedBuild: "325"))
        XCTAssertNil(S.ManualRecord.read([:], installedBuild: "325"))
        XCTAssertEqual(S.manualText("0.9.0"), "Wizard for Mac 0.9.0 needs a new download")
    }

    func testInstallRefusalsArePlainWords() {
        func refusal(ready: Bool = true, finish: Bool = false, preparing: Bool = false, recording: Bool = false,
                     work: Bool = false, foreign: Bool = false) -> String? {
            S.installRefusal(ready: ready, finishPending: finish, preparing: preparing, recording: recording, work: work,
                             foreignHost: foreign)
        }
        XCTAssertNil(refusal())
        XCTAssertNil(refusal(ready: false, finish: true))
        XCTAssertEqual(refusal(recording: true), "Recording is on. Update after it ends.")
        XCTAssertEqual(refusal(work: true), "Wizard is working. Update after it finishes.")
        XCTAssertEqual(refusal(ready: false), "No update is ready to install.")
        XCTAssertEqual(refusal(preparing: true), "An update is already being prepared.")
        XCTAssertNotNil(refusal(foreign: true))
    }

    func testStatusObjectHasEveryFieldAndNullsWhatDoesNotApply() throws {
        let checked = Date(timeIntervalSince1970: 1_795_000_000.123)
        let current = S.object(installedVersion: "0.8.14", installedBuild: "325", phase: "current",
                               latest: ("0.8.14", "325"), progress: nil, checkedAt: checked, waitingFor: nil,
                               manualURL: nil, error: nil)
        XCTAssertEqual(Set(current.keys), ["schema", "installed", "phase", "latest", "progress", "checkedAt", "waitingFor",
                                           "manual", "error", "channel"])
        XCTAssertEqual(current["schema"] as? Int, 1)
        XCTAssertEqual(current["installed"] as? [String: String], ["version": "0.8.14", "build": "325"])
        XCTAssertEqual(current["phase"] as? String, "current")
        XCTAssertEqual(current["checkedAt"] as? Int64, 1_795_000_000_123)
        for key in ["latest", "progress", "waitingFor", "manual", "error", "channel"] { XCTAssertTrue(current[key] is NSNull, key) }
        XCTAssertTrue(JSONSerialization.isValidJSONObject(current))

        let down = S.object(installedVersion: "0.8.14", installedBuild: "325", phase: "downloading", latest: ("0.8.15", "326"),
                            progress: 0.4249, checkedAt: nil, waitingFor: nil, manualURL: nil, error: nil)
        XCTAssertEqual(down["latest"] as? [String: String], ["version": "0.8.15", "build": "326"])
        XCTAssertEqual(down["progress"] as? Double, 0.42)

        let waiting = S.object(installedVersion: "0.8.14", installedBuild: "325", phase: "ready", latest: ("0.8.15", "326"),
                               progress: 1, checkedAt: nil, waitingFor: "recording", manualURL: nil, error: nil)
        XCTAssertEqual(waiting["waitingFor"] as? String, "recording")
        XCTAssertTrue(waiting["progress"] is NSNull)

        let manual = S.object(installedVersion: "0.8.14", installedBuild: "325", phase: "manual", latest: ("0.9.0", "330"),
                              progress: nil, checkedAt: nil, waitingFor: "work", manualURL: S.defaultDownloadURL, error: nil)
        XCTAssertEqual(manual["manual"] as? [String: String], ["url": "https://www.aiwizards.com/downloads"])
        XCTAssertTrue(manual["waitingFor"] is NSNull)
        let refused = S.object(installedVersion: "0.8.14", installedBuild: "325", phase: "manual", latest: ("0.9.0", "330"),
                               progress: nil, checkedAt: nil, waitingFor: nil, manualURL: "https://evil.example/", error: nil)
        XCTAssertTrue(refused["manual"] is NSNull)

        let failed = S.object(installedVersion: "0.8.14", installedBuild: "325", phase: "failed", latest: nil, progress: nil,
                              checkedAt: nil, waitingFor: nil, manualURL: nil, error: "Update failed — no network")
        XCTAssertEqual(failed["error"] as? String, "Update failed — no network")
        XCTAssertEqual(S.object(installedVersion: "", installedBuild: "", phase: "bogus", latest: nil, progress: nil,
                                checkedAt: nil, waitingFor: nil, manualURL: nil, error: nil)["phase"] as? String, "idle")
        _ = try JSONSerialization.data(withJSONObject: manual)
    }

    func testUrgentOnlyForACriticalReleaseOnItsWay() {
        // try-wizard#128: a critical release carries "urgent": true; otherwise the key is not there at all.
        func object(_ phase: String, urgent: Bool, latest: (version: String, build: String)? = ("0.8.16", "327")) -> [String: Any] {
            S.object(installedVersion: "0.8.15", installedBuild: "326", phase: phase, latest: latest, progress: nil,
                     checkedAt: nil, waitingFor: nil, manualURL: S.defaultDownloadURL, error: nil, urgent: urgent)
        }
        for phase in ["downloading", "verifying", "ready", "installing"] {
            XCTAssertEqual(object(phase, urgent: true)["urgent"] as? Bool, true, phase)
            XCTAssertNil(object(phase, urgent: false)["urgent"], phase)
        }
        for phase in ["idle", "checking", "current", "manual", "failed"] { XCTAssertNil(object(phase, urgent: true)["urgent"], phase) }
        XCTAssertNil(object("ready", urgent: true, latest: nil)["urgent"])
        XCTAssertTrue(JSONSerialization.isValidJSONObject(object("ready", urgent: true)))
    }
}
