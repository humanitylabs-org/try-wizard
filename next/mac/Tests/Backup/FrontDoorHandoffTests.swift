import XCTest
@testable import WizardBackupContract

final class FrontDoorHandoffTests: XCTestCase {
    let setup = URL(string: "http://127.0.0.1:48030/")!
    let ux = URL(string: "http://127.0.0.1:48023/")!
    let target = URL(string: "http://127.0.0.1:48023/wizard-os-home/?session=x")!

    func check(_ current: String?, _ to: URL, method: String? = "GET", mainFrame: Bool = true) -> Bool {
        FrontDoorHandoff.needsNativeLoad(from: current.flatMap { URL(string: $0) }, to: to, method: method,
                                         mainFrame: mainFrame, setup: setup, ux: ux)
    }

    func testStartChattingHandOffIsLoadedNatively() {
        XCTAssertTrue(check("http://127.0.0.1:48030/", target))
        XCTAssertTrue(check("http://127.0.0.1:48030/?step=4", target, method: nil))
        XCTAssertTrue(check("http://127.0.0.1:48030/", URL(string: "http://127.0.0.1:48023/wizard/")!, method: "get"))
    }

    func testEverythingElseIsLeftToWebKit() {
        // Already on Wizard, or not from the front door.
        XCTAssertFalse(check("http://127.0.0.1:48023/wizard-os-home/", target))
        XCTAssertFalse(check(nil, target))
        XCTAssertFalse(check("http://localhost:48023/apps/files/", target))
        // Not the main frame, not a GET.
        XCTAssertFalse(check("http://127.0.0.1:48030/", target, mainFrame: false))
        XCTAssertFalse(check("http://127.0.0.1:48030/", target, method: "POST"))
        // The isolated apps origin and other ports never get the native load.
        XCTAssertFalse(check("http://127.0.0.1:48030/", URL(string: "http://localhost:48023/apps/files/")!))
        XCTAssertFalse(check("http://127.0.0.1:48030/", URL(string: "http://127.0.0.1:48031/")!))
        XCTAssertFalse(check("http://127.0.0.1:48030/", URL(string: "https://127.0.0.1:48023/")!))
        XCTAssertFalse(check("http://127.0.0.1:48030/", URL(string: "https://example.com/")!))
    }
}
