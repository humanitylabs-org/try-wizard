import XCTest
@testable import WizardBackupContract

final class BackupContractTests: XCTestCase {
    let base = URL(string: "http://127.0.0.1:48030/")!

    func testSecretIsOnlyInBodyAndNativeHeaderHasNoOrigin() throws {
        let secret = "test-only-secret"
        let request = try WizardBackupContract.request(base: base, path: "jobs/abc/verify", method: "POST", body: ["secret": secret])
        XCTAssertEqual(request.url?.absoluteString, "http://127.0.0.1:48030/api/backup/jobs/abc/verify")
        XCTAssertFalse(request.url!.absoluteString.contains(secret))
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Wizard-Backup"), "wizardbackup-v1")
        XCTAssertNil(request.value(forHTTPHeaderField: "Origin"))
        let body = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: String]
        XCTAssertEqual(body["secret"], secret)
    }

    func testRemoteBaseAndQueryCannotReceiveSecret() {
        for url in ["https://example.invalid", "http://localhost:48030/", "http://127.0.0.1:48030/?secret=x", "http://owner:pass@127.0.0.1:48030/"] {
            XCTAssertThrowsError(try WizardBackupContract.request(base: URL(string: url)!, path: "export", method: "POST", body: ["secret": "test"]))
        }
        for path in ["export?secret=test", "../export", "http://evil.invalid", "/export"] {
            XCTAssertThrowsError(try WizardBackupContract.request(base: base, path: path))
        }
    }

    func testActivationConfirmationRemainsLiteralBoolean() throws {
        let request = try WizardBackupContract.request(base: base, path: "activate", method: "POST", body: ["old_is_off": true])
        let json = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
        XCTAssertEqual(json["old_is_off"] as? Bool, true)
        XCTAssertNil(request.url?.query)
    }

    func testDefaultFilenameIsSafeAndUsesBackupExtension() {
        let name = WizardBackupContract.filename(name: "../My Wizard/☃", date: Date(timeIntervalSince1970: 0))
        XCTAssertTrue(name.hasPrefix("My-Wizard-"))
        XCTAssertTrue(name.hasSuffix(".wizardbackup"))
        XCTAssertFalse(name.contains("/"))
        XCTAssertFalse(name.contains(".."))
        XCTAssertTrue(WizardBackupContract.filename(name: "").hasPrefix("Wizard-"))
    }

    func testPlanSummaryNamesCountsSizeAndPausedState() {
        let summary = WizardBackupContract.summary(["agents": ["one", "two"], "apps": ["files"],
            "files": ["count": 3, "bytes": 1200], "plan": ["install": ["files"], "replace": ["notes"], "leave": ["music"]]])
        for text in ["2 agents", "1 apps", "3 files", "one, two", "Install: files", "Replace app data: notes", "Leave unchanged: music", "paused", "undo"] {
            XCTAssertTrue(summary.contains(text), text)
        }
    }

    func testWarningIsVisibleAndEmptyPlanIsSafe() {
        XCTAssertTrue(WizardBackupContract.summary(["warnings_count": 2]).contains("2 compatibility"))
        XCTAssertTrue(WizardBackupContract.summary([:]).contains("0 agents"))
    }
}
