"""Static contracts, not WebKit/runtime acceptance.

DOWNLOAD_SOURCE overlays ONLY App/main.swift from the author. Helper, build and
XCTest artifacts still come from the candidate; this is not an author build.
Swift allocator tests do not exercise actual WKDownload gesture/frame metadata.
"""
import os
from pathlib import Path
import unittest

MAC = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("DOWNLOAD_SOURCE", MAC / "App/main.swift")).read_text()
HELPER = (MAC / "Shared/DownloadDestinations.swift").read_text()


class DownloadReservationContract(unittest.TestCase):
    def contains(self, text, fragment):
        self.assertTrue(fragment in text, f"Missing bounded source fragment: {fragment!r}")

    def section(self, start, end):
        self.contains(SOURCE, start)
        remainder = SOURCE.split(start, 1)[1]
        self.contains(remainder, end)
        return remainder.split(end, 1)[0]

    def before(self, text, first, second):
        self.contains(text, first)
        self.contains(text, second)
        self.assertLess(text.index(first), text.index(second), f"Expected {first!r} before {second!r}")

    def admission(self):
        return self.section("suggestedFilename: String, completionHandler:", "func downloadDidFinish")

    def test_admission_reserves_inflight_paths_before_completion(self):
        admission = self.admission()
        self.contains(admission, "downloadTargets.reserve(for: ObjectIdentifier(download)")
        self.before(admission, "downloadTargets.reserve", "completionHandler(target)")
        self.contains(HELPER, "targets.values.contains(where: { identity($0) == identity(target) }) || fileExists(target.path)")
        self.before(HELPER, "while targets.values.contains", "targets[download] = target")
        self.contains(admission, "FileManager.default.attributesOfItem(atPath: $0)")

    def test_canonical_case_identity_and_original_filename_storage(self):
        for fragment in ["precomposedStringWithCanonicalMapping", ".folding(options: [.caseInsensitive]",
                         'Locale(identifier: "en_US_POSIX")', "targets[download] = target"]:
            self.contains(HELPER, fragment)

    def test_actual_user_metadata_and_availability_precede_allocation(self):
        admission = self.admission()
        for fragment in ["guard #available(macOS 15.2, *) else { completionHandler(nil); return }",
                         "guard download.isUserInitiated,", "allowsNative(download.originatingFrame)",
                         "else { completionHandler(nil); return }"]:
            self.before(admission, fragment, "downloadTargets.reserve")
        self.before(admission, "else { completionHandler(nil); return }", "activeDownloads[ObjectIdentifier(download)] = download")
        self.assertFalse(".linkActivated" in admission, "Navigation type is not gesture metadata")

    def test_installed_frame_download_scope_does_not_grant_other_native_powers(self):
        self.contains(self.admission(), "(isTrustedDocument && Store.active?.kind == .thisMac &&\n                 NativeOrigin(download.originatingFrame.securityOrigin)?.isInstalledApp == true)")
        authority = self.section("func allowsNative(_ frame: WKFrameInfo)", "private func isWizardOrigin")
        self.contains(authority, "guard frame.isMainFrame, isTrustedDocument")
        self.contains(authority, "!origin.isInstalledApp")
        self.contains(SOURCE, "let allowed = allowsNative(frame) && NativeOrigin(origin) == NativeOrigin(frame.securityOrigin)")
        self.contains(SOURCE, "owner?.allowsNative(message.frameInfo) == true")

    def test_real_download_objects_retained_and_both_callbacks_release(self):
        self.contains(SOURCE, "private var activeDownloads: [ObjectIdentifier: WKDownload] = [:]")
        self.before(self.admission(), "activeDownloads[ObjectIdentifier(download)] = download", "downloadTargets.reserve")
        finish = self.section("func downloadDidFinish", "didFailWithError")
        failure = self.section("didFailWithError error: Error, resumeData:", "func webView")
        for callback in (finish, failure):
            self.contains(callback, "activeDownloads.removeValue(forKey: ObjectIdentifier(download))")
            self.contains(callback, "downloadTargets.release(ObjectIdentifier(download))")
        self.before(failure, "activeDownloads.removeValue", "NSURLErrorCancelled")
        self.before(failure, "downloadTargets.release", "NSURLErrorCancelled")
        self.contains(HELPER, "targets.removeValue(forKey: download)")

    def test_failure_is_authorized_non_cancelled_window_sheet(self):
        failure = self.section("didFailWithError error: Error, resumeData:", "func webView")
        self.contains(failure, "guard target != nil, (error as NSError).code != NSURLErrorCancelled, let window else { return }")
        self.contains(failure, "alert.beginSheetModal(for: window, completionHandler: nil)")
        self.assertFalse("runModal" in failure, "Downloads must not run an app-modal alert")

    def test_reveal_burst_is_coalesced_after_authorized_release(self):
        finish = self.section("func downloadDidFinish", "didFailWithError")
        self.before(finish, "guard let target = downloadTargets.release", "queueDownloadReveal(target)")
        self.assertNotIn("activateFileViewerSelecting", finish)
        reveal = self.section("private func queueDownloadReveal", "func downloadDidFinish")
        self.contains(reveal, "guard downloadReveals.append(target) else { return }")
        self.contains(reveal, "DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in")
        self.before(reveal, "let targets = self.downloadReveals.drain()", "activateFileViewerSelecting(targets)")
        for fragment in ["struct DownloadRevealBatch", "let shouldSchedule = pending.isEmpty",
                         "pending.append(target)", "return shouldSchedule", "defer { pending.removeAll() }"]:
            self.contains(HELPER, fragment)

    def test_author_download_routes_and_authorized_reveal_remain(self):
        for fragment in ["if action.shouldPerformDownload { decisionHandler(.download); return }",
                         '!response.canShowMIMEType || disposition.lowercased().hasPrefix("attachment")',
                         "navigationAction: WKNavigationAction, didBecome download: WKDownload",
                         "navigationResponse: WKNavigationResponse, didBecome download: WKDownload",
                         "NSWorkspace.shared.activateFileViewerSelecting(targets)",
                         "Couldn't download this file", ".downloadsDirectory, in: .userDomainMask",
                         'homeDirectoryForCurrentUser.appendingPathComponent("Downloads")']:
            self.contains(SOURCE, fragment)
        finish = self.section("func downloadDidFinish", "didFailWithError")
        self.before(finish, "guard let target = downloadTargets.release", "queueDownloadReveal(target)")

    def test_helper_is_in_real_build_and_existing_native_suite(self):
        self.contains((MAC / "build.sh").read_text(), "Shared/DownloadDestinations.swift")
        package = (MAC / "Package.swift").read_text()
        self.contains(package, '"DownloadDestinations.swift"')
        self.contains(package, 'path: "Tests/Backup"')
        tests = (MAC / "Tests/Backup/DownloadDestinationsTests.swift").read_text()
        for name in ["testRapidDuplicatesReserveBeforeBytesExistAndRelease", "testExistingFilesSuffixesAndExtensionlessNames",
                     "testFilenameStaysOneConfinedComponent", "testCaseAndCanonicalUnicodeReserveDistinctDestinations"]:
            self.contains(tests, name)


if __name__ == "__main__":
    unittest.main()
