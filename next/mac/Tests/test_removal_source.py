#!/usr/bin/env python3
"""Fast source guards only. They are not native compile or real VM acceptance."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RemovalSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = (ROOT / 'Shared/RemovalContract.swift').read_text()
        cls.native = (ROOT / 'App/WizardRemoval.swift').read_text()
        cls.app = (ROOT / 'App/main.swift').read_text()
        cls.host = (ROOT / 'Host/main.swift').read_text()
        cls.build = (ROOT / 'build.sh').read_text()

    def test_contract_has_no_ambient_wizard_state(self):
        for forbidden in ['WizardShared.', 'UserDefaults.', 'Process()', 'NSWorkspace.']:
            self.assertNotIn(forbidden, self.contract)
        for injected in ['let dataHome: URL', 'let files: [URL]', 'let bundleIDs: [String]', 'isStopped: () -> Bool', 'effects: WizardRemovalEffects']:
            self.assertIn(injected, self.contract)

    def test_keep_is_app_only(self):
        self.assertIn('var removesData: Bool { action != .keepData }', self.contract)
        self.assertIn('var entries: [Entry] { removesData ? inventory : [] }', self.contract)
        self.assertIn('if plan.removesData {', self.contract)
        self.assertIn('if plan.removesApp { try fence(); try effects.trash(plan.app) }', self.contract)

    def test_files_and_stop_fences(self):
        for fragment in ['Self.overlaps(target, folder)', 'Self.overlaps(resolved, folder.resolvingSymlinksInPath())', 'try plan.validate()', 'guard isStopped()']:
            self.assertIn(fragment, self.contract)
        self.assertIn('WizardShared.defaultFilesFolder, WizardShared.filesFolder', self.native)
        self.assertIn('try ownership.acquire()', self.native)
        self.assertNotIn('effects.remove(plan.files', self.contract)

    def test_authenticated_existing_host_handshake(self):
        for fragment in ['"pid": getpid()', '"peer": WizardRelease.peer', '"expires":', '"appPath":', 'WizardUpdate.request', 'HostControl.send("prepare-update")', 'response["nonce"] as? String == nonce', 'response["state"] as? String == "stopped"']:
            self.assertIn(fragment, self.native)
        self.assertNotIn('hostResponseURL', self.native)
        self.assertNotIn('prepare-update \\(nonce)', self.native)

    def test_no_host_kill_or_guest_changes(self):
        self.assertIsNone(re.search(r'\b(kill|terminate)\s*\(', self.native.replace('NSApp.terminate(', 'NSApp.exit(')))
        self.assertNotIn('/bin/rm', self.native)
        self.assertIn('clonefile(src.path, dst.path, 0)', self.native)
        self.assertIn('The APFS disk backup failed', self.native)
        self.assertIn('try fm.moveItem(at: url, to: retired)', self.native)
        self.assertIn('try fm.removeItem(at: retired)', self.native)

    def test_missing_original_app_uses_clean_stop(self):
        self.assertIn('withTimeInterval: 5', self.host)
        self.assertIn('vm.stop(forceOnTimeout: false, cleanTimeout: 45', self.host)
        self.assertIn('WizardMissingAppWatch(originalApp:', self.host)
        self.assertIn('@objc func quitAll()', self.host)  # preserve the existing selector
        self.assertIn('!fileExists(originalApp.appendingPathComponent("Contents/Info.plist").path)', self.contract)

    def test_both_binaries_link_contract_and_app_links_controller(self):
        lines = [line for line in self.build.splitlines() if line.startswith('"${SWIFTC[@]}" Shared/')]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all('Shared/RemovalContract.swift' in line for line in lines))
        self.assertIn('App/WizardRemoval.swift', lines[1])
        self.assertIn('Start Fresh…', self.app)
        self.assertIn('Uninstall Wizard…', self.app)

    def test_fixture_runner_does_not_launch_real_app(self):
        script = (ROOT / 'tools/qa-removal-native.sh').read_text()
        self.assertIn('Shared/RemovalContract.swift Tests/RemovalTests.swift', script)
        self.assertNotIn('open -', script)
        self.assertNotIn('defaults write', script)
        self.assertIn('NOT_RUN: real-app', script)
        tests = (ROOT / 'Tests/RemovalTests.swift').read_text()
        for label in ['Files inside DataHome', 'Files equal DataHome', 'Files around DataHome', 'external DataHome', 'running VM refuses', 'idempotent retry', 'clone failure']:
            self.assertIn(label, tests)


if __name__ == '__main__':
    unittest.main(verbosity=2)
