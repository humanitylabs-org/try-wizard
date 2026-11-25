import XCTest
@testable import WizardNowPlaying

/// try-wizard#142: Music and Podcasts (only) show in Now Playing; the media keys go back to the playing app.
final class NowPlayingTests: XCTestCase {
    typealias R = WizardNowPlayingRule

    func testOnlyMusicAndPodcastsByPath() {
        XCTAssertEqual(R.appId(path: "/wizard-music/"), "wizard-music")
        XCTAssertEqual(R.appId(path: "/wizard-music/index.html"), "wizard-music")
        XCTAssertEqual(R.appId(path: "/apps/wizard-podcasts/"), "wizard-podcasts")
        XCTAssertEqual(R.appId(path: "/apps/wizard-podcasts"), "wizard-podcasts")
        XCTAssertNil(R.appId(path: "/"))
        XCTAssertNil(R.appId(path: "/apps/"))
        XCTAssertNil(R.appId(path: "/wizard-youtube-music/"))
        XCTAssertNil(R.appId(path: "/apps/wizard-maps/"))
        XCTAssertNil(R.appId(path: "/wizard-musicx/"))
        XCTAssertNil(R.appId(path: "/files/wizard-music/"))
    }

    func testAdmitNeedsShellAndWizardAddress() {
        XCTAssertNil(R.admit(trustedShell: false, wizardAddress: true, path: "/wizard-music/"))
        XCTAssertNil(R.admit(trustedShell: true, wizardAddress: false, path: "/wizard-music/"))
        XCTAssertNil(R.admit(trustedShell: true, wizardAddress: true, path: "/apps/wizard-maps/"))
        XCTAssertEqual(R.admit(trustedShell: true, wizardAddress: true, path: "/apps/wizard-podcasts/"), "wizard-podcasts")
    }

    func testPodcastsSkipsMusicTracks() {
        let podcasts = R.commands(for: "wizard-podcasts")
        XCTAssertTrue(podcasts.contains(.skipBack) && podcasts.contains(.skipForward))
        XCTAssertFalse(podcasts.contains(.next) || podcasts.contains(.previous))
        let music = R.commands(for: "wizard-music")
        XCTAssertTrue(music.contains(.next) && music.contains(.previous))
        XCTAssertFalse(music.contains(.skipBack) || music.contains(.skipForward))
        for list in [podcasts, music] {
            XCTAssertTrue(list.contains(.play) && list.contains(.pause) && list.contains(.toggle) && list.contains(.seek))
        }
        XCTAssertEqual(R.commands(for: "wizard-maps"), [])
        XCTAssertEqual(R.skipBackSeconds, 15)
        XCTAssertEqual(R.skipForwardSeconds, 30)
    }

    func testScriptCarriesOnlyFixedNameAndFiniteNumber() {
        XCTAssertEqual(R.script(.seek, value: 12.5),
                       "(window.__wizardNowPlaying ? window.__wizardNowPlaying.command('seek', 12.5) : false) === true")
        XCTAssertTrue(R.script(.skipBack).contains("'skipBack', 15.0"))
        XCTAssertTrue(R.script(.skipForward).contains("'skipForward', 30.0"))
        XCTAssertTrue(R.script(.seek, value: .nan).contains("'seek', 0.0"))
        XCTAssertTrue(R.script(.seek, value: .infinity).contains("'seek', 0.0"))
    }

    func testOpenScriptOnlyForTheTwoApps() {
        XCTAssertNotNil(R.openScript("wizard-podcasts"))
        XCTAssertTrue(R.openScript("wizard-music")!.contains("o('wizard-music')"))
        XCTAssertNil(R.openScript("wizard-maps"))
        XCTAssertNil(R.openScript("x'); alert(1); ('"))
    }

    func testOwnerFollowsWhatPlays() {
        XCTAssertNil(R.owner(current: nil, report: "wizard-music", playing: false, gone: false))
        XCTAssertEqual(R.owner(current: nil, report: "wizard-music", playing: true, gone: false), "wizard-music")
        XCTAssertEqual(R.owner(current: "wizard-music", report: "wizard-music", playing: false, gone: false), "wizard-music")
        XCTAssertEqual(R.owner(current: "wizard-music", report: "wizard-podcasts", playing: true, gone: false), "wizard-podcasts")
        XCTAssertEqual(R.owner(current: "wizard-podcasts", report: "wizard-music", playing: false, gone: false), "wizard-podcasts")
        XCTAssertEqual(R.owner(current: "wizard-podcasts", report: "wizard-music", playing: false, gone: true), "wizard-podcasts")
        XCTAssertNil(R.owner(current: "wizard-podcasts", report: "wizard-podcasts", playing: false, gone: true))
    }

    func testStateIsCleaned() {
        XCTAssertNil(R.State(["playing": true]))
        let s = R.State(["v": 1, "playing": true, "title": "  Episode 1 ", "artist": "The Show", "album": "Podcasts",
                         "artwork": "https://cdn.example/art.jpg", "duration": 100.0, "position": 140.0, "rate": 1.5])!
        XCTAssertTrue(s.playing)
        XCTAssertEqual(s.title, "Episode 1")
        XCTAssertEqual(s.artist, "The Show")
        XCTAssertEqual(s.artwork?.absoluteString, "https://cdn.example/art.jpg")
        XCTAssertEqual(s.duration, 100)
        XCTAssertEqual(s.position, 100)
        XCTAssertEqual(s.rate, 1.5)

        let bad = R.State(["v": 1, "title": String(repeating: "a", count: 5000), "artwork": "javascript:alert(1)",
                           "duration": Double.nan, "position": -3.0, "rate": 99.0])!
        XCTAssertFalse(bad.playing)
        XCTAssertEqual(bad.title.count, R.State.maxText)
        XCTAssertNil(bad.artwork)
        XCTAssertEqual(bad.duration, 0)
        XCTAssertEqual(bad.position, 0)
        XCTAssertEqual(bad.rate, 1)
        XCTAssertNil(R.State(["v": 1, "artwork": "file:///etc/passwd"])!.artwork)

        let gone = R.State(["v": 1, "gone": true, "playing": true])!
        XCTAssertTrue(gone.gone)
        XCTAssertFalse(gone.playing)
    }

    func testFallbackTitle() {
        XCTAssertEqual(R.fallbackTitle("wizard-podcasts"), "Podcasts")
        XCTAssertEqual(R.fallbackTitle("wizard-music"), "Music")
    }
}
