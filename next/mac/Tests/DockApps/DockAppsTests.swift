import XCTest
@testable import WizardDockApps

/// try-wizard#147: every Wizard app as its own Dock icon, opening that app alone in its own WizardOS window.
final class DockAppsTests: XCTestCase {
    typealias R = WizardDockAppsRule

    func testAppIdsFollowTheShellRule() {
        XCTAssertTrue(R.validId("wizard-notes"))
        XCTAssertTrue(R.validId("TG_style-2"))
        XCTAssertFalse(R.validId(""))
        XCTAssertFalse(R.validId("-notes"))
        XCTAssertFalse(R.validId("notes/../x"))
        XCTAssertFalse(R.validId("notes'; rm -rf ~"))
        XCTAssertFalse(R.validId(String(repeating: "a", count: 97)))
        XCTAssertTrue(R.validRequestId("12"))
        XCTAssertFalse(R.validRequestId("1x"))
    }

    func testLaunchLinksRoundTrip() {
        let url = R.launchURL(appId: "wizard-notes")!
        XCTAssertEqual(url.absoluteString, "wizard://app/wizard-notes")
        XCTAssertEqual(R.parse(url)?.appId, "wizard-notes")
        XCTAssertEqual(R.parse(url)?.path, "")
        let deep = R.launchURL(appId: "wizard-notes", path: "/apps/wizard-notes/#n1")!
        XCTAssertEqual(R.parse(deep)?.path, "/apps/wizard-notes/#n1")
        XCTAssertNil(R.parse(URL(string: "wizard://connect?origin=x")!))
        XCTAssertNil(R.parse(URL(string: "wizard://app/a/b")!))
        XCTAssertNil(R.parse(URL(string: "https://app/wizard-notes")!))
        XCTAssertEqual(R.parse(URL(string: "wizard://app/x?path=//evil.example/")!)?.path, "")
        XCTAssertNil(R.launchURL(appId: "../x"))
    }

    func testSessionURLIsTheAndroidOneAppPage() {
        let home = URL(string: "http://127.0.0.1:48023/wizard-os-home/")!
        XCTAssertEqual(R.sessionURL(home: home, appId: "wizard-notes")?.absoluteString,
                       "http://127.0.0.1:48023/wizard-os-home/?app-session=wizard-notes")
        let desktop = URL(string: "https://box.example/wizard-os-home/desktop.html#x")!
        XCTAssertEqual(R.sessionURL(home: desktop, appId: "tg")?.absoluteString, "https://box.example/wizard-os-home/?app-session=tg")
        let deep = R.sessionURL(home: home, appId: "wizard-notes", path: "/apps/wizard-notes/n/1")!
        let items = URLComponents(url: deep, resolvingAgainstBaseURL: false)!.queryItems!
        XCTAssertEqual(items.first { $0.name == "app-path" }?.value, "/apps/wizard-notes/n/1")
        XCTAssertNil(R.sessionURL(home: home, appId: "bad id"))
    }

    func testNamesAreSafeFileNames() {
        XCTAssertEqual(R.cleanName("  Notes ", appId: "n"), "Notes")
        XCTAssertEqual(R.cleanName("A/B:C", appId: "n"), "A-B-C")
        XCTAssertEqual(R.cleanName("..hidden", appId: "n"), "hidden")
        XCTAssertNil(R.cleanName("   ", appId: "n"))
        XCTAssertNil(R.cleanName(String(repeating: "x", count: 81), appId: "n"))
        XCTAssertEqual(R.bundleName(name: "Notes", appId: "n", takenByOthers: []), "Notes.app")
        XCTAssertEqual(R.bundleName(name: "Notes", appId: "n2", takenByOthers: ["notes.app"]), "Notes (n2).app")
    }

    func testLauncherIsThin() {
        let plist = R.infoPlist(appId: "wizard-notes", name: "Notes", version: "0.8.3", iconSHA: "abc")
        XCTAssertEqual(plist["CFBundleIdentifier"] as? String, "org.humanitylabs.wizard.app.wizard-notes")
        XCTAssertEqual(plist["CFBundleExecutable"] as? String, "launch")
        XCTAssertEqual(plist["LSUIElement"] as? Bool, true)
        XCTAssertEqual(plist[R.appIdKey] as? String, "wizard-notes")
        let script = R.launchScript(appId: "wizard-notes")!
        XCTAssertTrue(script.hasPrefix("#!/bin/sh\n"))
        XCTAssertTrue(script.contains("exec /usr/bin/open -b org.humanitylabs.wizard.mvp 'wizard://app/wizard-notes'"))
        XCTAssertNil(R.launchScript(appId: "x' ; rm"))
    }

    func testIcnsContainer() {
        let png = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 1, 2])
        let icns = R.icns([("ic07", png), ("bad", png), ("ic08", png)])
        XCTAssertEqual(Array(icns.prefix(4)), Array("icns".utf8))
        XCTAssertEqual(icns.count, 8 + 2 * (8 + png.count))
        XCTAssertEqual(Array(icns[4..<8]), [0, 0, 0, UInt8(icns.count)])
        XCTAssertEqual(Array(icns[8..<12]), Array("ic07".utf8))
        XCTAssertEqual(R.iconPNG("data:image/png;base64," + png.base64EncodedString()), png)
        XCTAssertNil(R.iconPNG("data:image/jpeg;base64," + png.base64EncodedString()))
        XCTAssertNil(R.iconPNG("data:image/png;base64," + Data("GIF89a".utf8).base64EncodedString()))
    }

    func testDockEntries() {
        let bundle = URL(fileURLWithPath: "/Users/a/Applications/Wizard Apps/Notes.app", isDirectory: true)
        let entry = R.dockEntry(for: bundle)
        let apps: [[String: Any]] = [["tile-data": ["file-data": ["_CFURLString": "file:///Applications/Safari.app/"]]], entry]
        XCTAssertEqual(R.dockIndex(of: bundle, in: apps), 1)
        XCTAssertNil(R.dockIndex(of: URL(fileURLWithPath: "/Users/a/Applications/Wizard Apps/Other.app"), in: apps))
        let tile = entry["tile-data"] as? [String: Any]
        XCTAssertEqual(tile?["file-label"] as? String, "Notes")
    }

    func testLinksBetweenAppWindows() {
        let box: Set<String> = ["http://127.0.0.1:48023", "http://localhost:48023"]
        let roots = ["wizard-notes": "/apps/wizard-notes/", "wizard-calendar": "/wizard-calendar/index.html", "tg": "/tg/"]
        func r(_ s: String, _ app: String = "wizard-notes") -> R.LinkRoute { R.route(URL(string: s)!, currentApp: app, boxOrigins: box, appRoots: roots) }
        XCTAssertEqual(r("http://localhost:48023/apps/wizard-notes/n/1"), .stay)
        XCTAssertEqual(r("http://localhost:48023/wizard-calendar/event/5?x=1"), .otherApp(id: "wizard-calendar", path: "/wizard-calendar/event/5?x=1"))
        XCTAssertEqual(r("http://127.0.0.1:48023/tg/#chat"), .otherApp(id: "tg", path: "/tg/#chat"))
        XCTAssertEqual(r("http://127.0.0.1:48023/wizard-os-home/?open=tg"), .otherApp(id: "tg", path: ""))
        XCTAssertEqual(r("http://127.0.0.1:48023/wizard-os-home/?session=abc"), .shell(path: "/wizard-os-home/?session=abc"))
        XCTAssertEqual(r("http://127.0.0.1:48023/wizard-os-home/?app-session=wizard-notes"), .stay)
        XCTAssertEqual(r("https://example.com/"), .external)
        XCTAssertEqual(r("http://127.0.0.1:9999/tg/"), .external)
        XCTAssertEqual(r("mailto:a@b.c"), .external)
        XCTAssertEqual(r("about:blank"), .stay)
        XCTAssertEqual(r("http://127.0.0.1:48023/unknown/"), .stay)
        XCTAssertEqual(r("http://127.0.0.1:48023/tg/%2e%2e/apps/"), .stay)
    }
}
