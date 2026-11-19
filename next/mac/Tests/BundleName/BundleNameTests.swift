import XCTest
@testable import WizardBundleName

/// try-wizard#124: Macs updated from builds before 0.8.0 still run from `Wizard MVP.app`, so the Dock, Cmd-Tab and
/// Finder say "Wizard MVP". The app renames its own bundle to WizardOS.app only when that is safe, and never
/// touches anything but the .app itself.
final class BundleNameTests: XCTestCase {
    var dir: URL!
    let fm = FileManager.default

    override func setUpWithError() throws {
        dir = fm.temporaryDirectory.appendingPathComponent("bundle-name-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
    }
    override func tearDownWithError() throws {
        try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.path)
        try? fm.removeItem(at: dir)
    }

    func makeApp(_ name: String) throws -> URL {
        let app = dir.appendingPathComponent(name, isDirectory: true)
        try fm.createDirectory(at: app.appendingPathComponent("Contents/MacOS"), withIntermediateDirectories: true)
        try Data("<plist/>".utf8).write(to: app.appendingPathComponent("Contents/Info.plist"))
        try Data("binary".utf8).write(to: app.appendingPathComponent("Contents/MacOS/Wizard"))
        return app
    }
    func facts(_ app: URL, host: Bool = false, other: Bool = false, phase: String? = nil) -> WizardBundleName.Facts {
        .init(bundle: app, hostRunning: host, otherAppRunning: other, updatePhase: phase)
    }
    func target(_ f: WizardBundleName.Facts) -> URL? {
        WizardBundleName.renameTarget(f, exists: { self.fm.fileExists(atPath: $0) }, writable: { self.fm.isWritableFile(atPath: $0) })
    }

    func testLegacyBundleIsRenamedInPlaceWithItsContents() throws {
        let old = try makeApp("Wizard MVP.app")
        let data = dir.appendingPathComponent("Wizard MVP", isDirectory: true)   // stands in for the data folder
        try fm.createDirectory(at: data, withIntermediateDirectories: true)
        let t = try XCTUnwrap(target(facts(old)))
        XCTAssertEqual(t.lastPathComponent, "WizardOS.app")
        XCTAssertEqual(t.deletingLastPathComponent().standardizedFileURL.path, dir.standardizedFileURL.path)
        XCTAssertTrue(WizardBundleName.rename(old, to: t))
        XCTAssertFalse(fm.fileExists(atPath: old.path))
        XCTAssertEqual(try Data(contentsOf: t.appendingPathComponent("Contents/MacOS/Wizard")), Data("binary".utf8))
        XCTAssertTrue(fm.fileExists(atPath: data.path), "only the .app moves")
        XCTAssertNil(target(facts(t)), "already WizardOS.app: nothing more to do")
    }

    func testOtherNamesAreLeftAlone() throws {
        for name in ["WizardOS.app", "Wizard.app", "My Wizard.app", "Wizard MVP 2.app"] {
            XCTAssertNil(target(facts(try makeApp(name))), name)
        }
    }

    func testNotRenamedWhileSomethingHoldsTheOldPath() throws {
        let old = try makeApp("Wizard MVP.app")
        XCTAssertNil(target(facts(old, host: true)), "Host running from inside the bundle")
        XCTAssertNil(target(facts(old, other: true)), "another copy of the app is open")
        for phase in ["prepared", "installing", "guest-activating"] {
            XCTAssertNil(target(facts(old, phase: phase)), phase)
        }
        XCTAssertNotNil(target(facts(old, phase: "native-activated")))
    }

    func testNeverReplacesAnExistingWizardOSApp() throws {
        let old = try makeApp("Wizard MVP.app")
        _ = try makeApp("WizardOS.app")
        XCTAssertNil(target(facts(old)))
    }

    func testReadOnlyOrTranslocatedCopiesAreLeftAlone() throws {
        let old = try makeApp("Wizard MVP.app")
        XCTAssertNil(WizardBundleName.renameTarget(facts(old), exists: { _ in false }, writable: { _ in false }))
        let translocated = URL(fileURLWithPath: "/private/var/folders/x/AppTranslocation/ABC/d/Wizard MVP.app")
        XCTAssertNil(WizardBundleName.renameTarget(facts(translocated), exists: { _ in false }, writable: { _ in true }))
    }

    func testFailedRenameLeavesTheBundle() throws {
        let old = try makeApp("Wizard MVP.app")
        let elsewhere = dir.appendingPathComponent("missing/WizardOS.app")
        XCTAssertFalse(WizardBundleName.rename(old, to: elsewhere))
        XCTAssertTrue(fm.fileExists(atPath: old.appendingPathComponent("Contents/MacOS/Wizard").path))
    }
}
