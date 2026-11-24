import XCTest
@testable import WizardBundledGuestUpdate

/// try-wizard#162: an app installed by hand from the DMG over an existing Wizard applies the guest update it
/// carries once, and never again for the same release and disk.
final class BundledGuestUpdateTests: XCTestCase {
    let thisRelease = "0.8.7-318"
    let disk = "16777232:4242"
    // What Jan's 0.8.0 Mac had after dragging in 0.8.5: the failed in-app update's journal and no receipt.
    var leftover: [String: Any] { ["phase": "install-failed", "from": "310", "to": "316", "releaseID": "0.8.5-316", "nonce": "n1"] }

    func decide(_ receipt: [String: Any] = [:], journal: [String: Any]? = nil, marker: [String: Any] = [:],
                carries: Bool = true, identity: String? = "16777232:4242") -> WizardBundledGuestUpdate.Decision {
        WizardBundledGuestUpdate.decide(releaseID: thisRelease, carriesGuest: carries, diskIdentity: identity,
                                        receipt: receipt, journal: journal ?? leftover, marker: marker)
    }

    func testHandInstallOverAnOlderWizardAppliesOnce() {
        XCTAssertEqual(decide(), .applyNow)
        // An older release's receipt on this disk is not this release.
        XCTAssertEqual(decide(["diskIdentity": disk, "releaseID": "0.8.5-316", "transactionNonce": "n0"]), .applyNow)
    }

    func testOpeningAgainAfterSuccessDoesNothing() {
        let receipt: [String: Any] = ["diskIdentity": disk, "releaseID": thisRelease, "transactionNonce": "n2",
                                      "managed_runtime_image": "x"]
        let journal: [String: Any] = ["kind": "hand-install", "phase": "guest-activated", "releaseID": thisRelease,
                                      "diskIdentity": disk, "nonce": "n2"]
        XCTAssertEqual(decide(receipt, journal: journal), .received)
        // ...also once a later, unrelated transaction has replaced the journal.
        XCTAssertEqual(decide(receipt, journal: leftover), .received)
    }

    func testAnInAppUpdateOfThisReleaseBeforeReceiptsNamedTheirReleaseCounts() {
        let receipt: [String: Any] = ["diskIdentity": disk, "transactionNonce": "n3"]
        let journal: [String: Any] = ["phase": "guest-activated", "releaseID": thisRelease, "diskIdentity": disk, "nonce": "n3"]
        XCTAssertEqual(decide(receipt, journal: journal), .received)
        // The nonce must belong to that transaction, and the receipt to this disk.
        XCTAssertEqual(decide(["diskIdentity": disk, "transactionNonce": "other"], journal: journal), .applyNow)
        XCTAssertEqual(decide(["diskIdentity": "1:1", "transactionNonce": "n3"], journal: journal), .applyNow)
    }

    func testAReceiptForAnotherDiskIsNotThisDisk() {
        XCTAssertEqual(decide(["diskIdentity": "1:99", "releaseID": thisRelease]), .applyNow)
    }

    func testAFailedAutomaticTryIsOfferedNotRepeated() {
        XCTAssertEqual(decide(marker: ["releaseID": thisRelease, "state": "attempted"]), .offer)
        // A try for an older release doesn't hold this one back.
        XCTAssertEqual(decide(marker: ["releaseID": "0.8.6-317", "state": "attempted"]), .applyNow)
        // An in-app or fresh-install update of this release that rolled back is offered too.
        let rolledBack: [String: Any] = ["kind": "fresh-install", "phase": "guest-rolled-back", "releaseID": thisRelease]
        XCTAssertEqual(decide(journal: rolledBack), .offer)
    }

    func testNothingToDoWithoutAGuestUpdateOrADisk() {
        XCTAssertEqual(decide(carries: false), .received)
        XCTAssertEqual(decide(identity: nil), .received)
        XCTAssertEqual(WizardBundledGuestUpdate.decide(releaseID: "", carriesGuest: true, diskIdentity: disk,
                                                       receipt: [:], journal: [:], marker: [:]), .received)
    }
}
