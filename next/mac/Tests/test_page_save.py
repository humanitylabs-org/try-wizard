"""Static contract for files.save (try-wizard#139), not WebKit/runtime acceptance.

A photo's Save in the shell's media viewer fetches the file, then clicks a blob <a download>. That click carries
no user gesture, so the WKDownload path (which requires isUserInitiated on macOS 15.2+) dropped it silently. The
shell now hands the bytes to the app over the native bridge and shows the app's honest answer.
"""
from pathlib import Path
import unittest

MAC = Path(__file__).resolve().parents[1]
SOURCE = (MAC / "App/main.swift").read_text()


def section(start, end):
    assert start in SOURCE, start
    rest = SOURCE.split(start, 1)[1]
    assert end in rest, end
    return rest.split(end, 1)[0]


class PageSaveContract(unittest.TestCase):
    def test_bridge_registers_files_prefix_on_the_window(self):
        init = section("NativeBridge.shared.owner = self", "dragView.owner = self")
        self.assertIn('NativeBridge.shared.register("files.")', init)
        self.assertIn('method == "files.save"', init)
        self.assertIn("self.saveFromPage(params, reply: reply)", init)

    def test_only_admitted_frames_reach_handlers(self):
        bridge = section("func userContentController(_ controller: WKUserContentController", "// MARK: - Local voice")
        self.assertLess(bridge.index("guard admitted else { return }"), bridge.index("handlers.first(where:"))
        self.assertIn("owner?.allowsNative(message.frameInfo) == true", bridge)

    def test_save_never_overwrites_and_replies_honestly(self):
        save = section("func saveFromPage(", "func downloadDidFinish(")
        self.assertIn("pageSaveMaxBase64", save)
        self.assertIn("downloadTargets.reserve(for: key", save)
        self.assertIn(".downloadsDirectory", save)
        self.assertIn("[.withoutOverwriting]", save)
        self.assertIn('reply(["status": "failed"', save)
        self.assertIn('reply(["status": "saved", "name": target.lastPathComponent', save)
        self.assertIn("downloadTargets.release(key)", save)
        self.assertIn("queueDownloadReveal(target)", save)
        # The failure reply comes before any reveal: a failed write never shows a Finder window.
        self.assertLess(save.index('if let failure { reply(["status": "failed"'), save.index("queueDownloadReveal(target)"))


if __name__ == "__main__":
    unittest.main()
