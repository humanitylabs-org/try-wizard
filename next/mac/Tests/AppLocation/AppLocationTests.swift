import XCTest
@testable import WizardAppLocation

/// try-wizard#135: Maps' locate button may show macOS's location prompt once; every other caller is denied silently.
final class AppLocationTests: XCTestCase {
    typealias R = WizardAppLocationRule

    func testOnlyTheWizardShellAtTheWizardAddressMayAsk() {
        XCTAssertEqual(R.decide(trustedShell: false, wizardAddress: true, access: .notAsked), .deny)
        XCTAssertEqual(R.decide(trustedShell: true, wizardAddress: false, access: .notAsked), .deny)
        XCTAssertEqual(R.decide(trustedShell: false, wizardAddress: false, access: .allowed), .deny)
    }

    func testFirstAskShowsMacOSPromptAndGrantsOnlyOnYes() {
        XCTAssertEqual(R.decide(trustedShell: true, wizardAddress: true, access: .notAsked), .askMacOS)
        XCTAssertEqual(R.afterPrompt(.allowed), .grant)
        XCTAssertEqual(R.afterPrompt(.refused), .deny)
        XCTAssertEqual(R.afterPrompt(.notAsked), .deny)
    }

    func testAcceptedOnceThenFollowsWithoutAnotherPrompt() {
        XCTAssertEqual(R.decide(trustedShell: true, wizardAddress: true, access: .allowed), .grant)
    }

    func testDeniedInMacOSStaysDeniedWithNoPrompt() {
        XCTAssertEqual(R.decide(trustedShell: true, wizardAddress: true, access: .refused), .deny)
    }

    func testCoreLocationStatusMapping() {
        XCTAssertEqual(R.Access(rawStatus: 0), .notAsked)
        XCTAssertEqual(R.Access(rawStatus: 1), .refused)
        XCTAssertEqual(R.Access(rawStatus: 2), .refused)
        XCTAssertEqual(R.Access(rawStatus: 3), .allowed)
        XCTAssertEqual(R.Access(rawStatus: 4), .allowed)
        XCTAssertEqual(R.Access(rawStatus: 99), .refused)
    }
}
