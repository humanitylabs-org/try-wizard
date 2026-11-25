#!/usr/bin/env python3
"""try-wizard#177: a fresh Mac install downloads WizardOS to files before unpacking, and says why when it can't.

The behaviour of the download itself (hash per part, retries, kept parts, whole-archive check) is tested by the
XCTest in Tests/OSDownload; this checks the app is wired to it.
"""
import pathlib
import re
import unittest

MAC = pathlib.Path(__file__).resolve().parents[1]
MAIN = (MAC / 'App/main.swift').read_text()


def body(signature):
    start = MAIN.index(signature)
    left = MAIN.index('{', start)
    depth, i = 1, left + 1
    while depth:
        depth += (MAIN[i] == '{') - (MAIN[i] == '}')
        i += 1
    return MAIN[start:i]


class FreshMacDownload(unittest.TestCase):
    def test_download_never_writes_into_tar(self):
        installer = MAIN[MAIN.index('final class OSInstaller'):MAIN.index('// MARK: - Wizard Host (back-end service) control')]
        self.assertIn('final class OSInstaller: NSObject {', installer)
        self.assertNotIn('URLSessionDataDelegate', installer)
        self.assertNotIn('didReceive data', installer)
        install = body('    func install() {')
        self.assertIn('WizardOSDownload(items:', install)
        self.assertIn('self.unpack(files)', install)
        self.assertNotIn('startTar', install)
        # The kept download needs room too.
        self.assertIn('checkFreeSpace(install: feed.totalInstallBytes + archiveBytes)', install)

    def test_download_is_removed_only_once_os_is_in_place(self):
        complete = body('    private func completeTar(error: Error?)')
        self.assertRegex(complete, r'if case \.success = r, let folder = self\.downloadFolder \{ try\? FileManager\.default\.removeItem\(at: folder\) \}')

    def test_get_os_screen_says_why_and_offers_try_again(self):
        flow = body('    func installOnThisMac()')
        self.assertIn('self.showGetOS(note: err.localizedDescription)', flow)
        self.assertNotIn('note: bad ?', flow)
        screen = body('    func showGetOS(')
        self.assertNotIn('0.3.0', screen)
        self.assertIn('installer.feedVersion', screen)
        actions = re.findall(r'\("([^"]+)", #selector\((\w+)\)\)', screen)
        self.assertEqual(actions[0], ('Try Again', 'retryInstall'))
        self.assertIn(('Choose Downloaded File…', 'chooseOSFile'), actions)
        self.assertNotIn('wizard-os-0.3.0', MAIN)

    def test_window_capture_draws_in_the_window_appearance(self):
        snap = body('    func snapshot(to path: String)')
        self.assertIn('effectiveAppearance.performAsCurrentDrawingAppearance', snap)

    def test_shared_file_is_built_and_tested(self):
        build = (MAC / 'build.sh').read_text()
        app_line = next(l for l in build.splitlines() if 'App/main.swift' in l and 'SWIFTC' in l)
        self.assertIn('Shared/OSDownload.swift', app_line)
        pkg = (MAC / 'Package.swift').read_text()
        self.assertIn('sources: ["OSDownload.swift"]', pkg)
        self.assertIn('path: "Tests/OSDownload"', pkg)


if __name__ == '__main__':
    unittest.main()
