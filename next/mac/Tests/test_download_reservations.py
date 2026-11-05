"""Source contracts only; real allocator behavior is covered by hosted Swift XCTest."""
import os
from pathlib import Path
import unittest

MAC = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("DOWNLOAD_SOURCE", MAC / "App/main.swift")).read_text()
HELPER = (MAC / "Shared/DownloadDestinations.swift").read_text()


class DownloadReservationContract(unittest.TestCase):
    def test_admission_reserves_inflight_paths_before_completion(self):
        self.assertIn("downloadTargets.reserve(for: ObjectIdentifier(download)", SOURCE,
                      "Destination admission must reserve paths even before any bytes exist")
        self.assertIn("while targets.values.contains(target) || fileExists(target.path)", HELPER)
        self.assertLess(HELPER.index("targets[download] = target"), HELPER.index("return target", HELPER.index("targets[download] = target")))
        admission = SOURCE.split("suggestedFilename: String, completionHandler:", 1)[1].split("func downloadDidFinish", 1)[0]
        self.assertLess(admission.index("downloadTargets.reserve"), admission.index("completionHandler(target)"))

    def test_both_terminal_callbacks_release(self):
        finish = SOURCE.split("func downloadDidFinish", 1)[1].split("didFailWithError", 1)[0]
        failure = SOURCE.split("didFailWithError error: Error, resumeData:", 1)[1].split("func webView", 1)[0]
        for callback in (finish, failure):
            self.assertIn("downloadTargets.release(ObjectIdentifier(download))", callback)
        self.assertIn("targets.removeValue(forKey: download)", HELPER)

    def test_author_download_routes_reveal_and_alert_remain(self):
        for fragment in ["if action.shouldPerformDownload { decisionHandler(.download); return }",
                         "!response.canShowMIMEType || disposition.lowercased().hasPrefix(\"attachment\")",
                         "navigationAction: WKNavigationAction, didBecome download: WKDownload",
                         "navigationResponse: WKNavigationResponse, didBecome download: WKDownload",
                         "NSWorkspace.shared.activateFileViewerSelecting([target])",
                         "Couldn't download this file", ".downloadsDirectory, in: .userDomainMask",
                         'homeDirectoryForCurrentUser.appendingPathComponent("Downloads")']:
            self.assertIn(fragment, SOURCE)

    def test_helper_is_in_real_build_and_existing_native_suite(self):
        self.assertIn("Shared/DownloadDestinations.swift", (MAC / "build.sh").read_text())
        self.assertIn('"DownloadDestinations.swift"', (MAC / "Package.swift").read_text())
        self.assertIn('path: "Tests/Backup"', (MAC / "Package.swift").read_text())
        tests = (MAC / "Tests/Backup/DownloadDestinationsTests.swift").read_text()
        for name in ["testRapidDuplicatesReserveBeforeBytesExistAndRelease", "testExistingFilesSuffixesAndExtensionlessNames", "testFilenameStaysOneConfinedComponent"]:
            self.assertIn(name, tests)


if __name__ == "__main__":
    unittest.main()
