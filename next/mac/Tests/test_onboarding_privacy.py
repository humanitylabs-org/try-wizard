#!/usr/bin/env python3
"""Source-owned invariants; native execution is a separate admitted test."""
import argparse
from pathlib import Path
import sys
import unittest
from test_host_launch_errors import body

ROOT = Path(__file__).resolve().parents[1]

class OnboardingPrivacy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / 'App/main.swift').read_text()
        cls.host = (ROOT / 'Host/main.swift').read_text()
        cls.shared = (ROOT / 'Shared/Shared.swift').read_text()

    def test_startup_does_not_require_or_pick_a_host_folder(self):
        start = body(self.app, 'func begin()')
        self.assertNotIn('filesFolder', start)
        self.assertNotIn('askFilesFolder', start)
        self.assertNotIn('chooseFilesFolder', start)
        self.assertNotIn('If macOS asks whether Wizard may access a folder, click Allow.', self.app)

    def test_unfinished_legacy_selection_is_not_download_consent(self):
        start = body(self.app, 'func begin()')
        self.assertIn('WizardShared.osInstalled || Store.d.bool(forKey: "localHostingConfirmed")', start)
        self.assertLess(start.index('localHostingConfirmed'), start.index('installOnThisMac()'))
        self.assertIn('Store.d.set(true, forKey: "localHostingConfirmed")', body(self.app, 'func chooseThisMac()'))

    def test_actual_start_fresh_explicitly_resets_in_memory_route(self):
        self.assertIn('controller.startFreshOnboarding()', self.app)
        fresh = body(self.app, 'func startFreshOnboarding()')
        self.assertIn('Store.backends = []', fresh)
        self.assertIn('removeObject(forKey: "localHostingConfirmed")', fresh)
        self.assertIn('showChooser()', fresh)
        removal = (ROOT / 'App/WizardRemoval.swift').read_text()
        self.assertLess(removal.index('finishStorageCleanup(plan'), removal.index('self.didStartFresh()'))

    def test_share_consent_precedes_filesystem_and_restart(self):
        share = body(self.app, 'func setFilesFolder(_ url: URL)')
        for operation in ['createDirectory', 'WizardShared.setFilesFolder', 'HostControl.send("restart")']:
            self.assertLess(share.index('alert.runModal()'), share.index(operation))
            self.assertLess(share.index('guard allowed, Store.active == selectedBackend'), share.index(operation))
        gate = body(self.app, 'func admitSharedFolderRestart')
        for required in ['backup?.isBusy', 'hasPendingWork', 'MeetingRecorder.shared.isRecording', 'admitUpdateRestart {', 'hasForeignRunner', 'done(allowed && nativeIdle())']:
            self.assertIn(required, gate)
        explicit = body(self.app, 'func askFilesFolder')
        self.assertNotIn('defaultFilesFolder', explicit)
        self.assertNotIn('fetchSizeNote', explicit)
        self.assertIn('not moved or deleted', explicit)

    def test_existing_single_folder_mount_and_upload_remain(self):
        self.assertIn('if let folder = WizardShared.activeSharedFolder', self.host)
        self.assertIn('VZSingleDirectoryShare(directory: VZSharedDirectory(url: folder, readOnly: false))', self.host)
        upload = body(self.app, 'func webView(_ webView: WKWebView, runOpenPanelWith')
        self.assertIn('panel.beginSheetModal', upload)
        self.assertNotIn('setFilesFolder', upload)
        self.assertIn('try d.write(to: filesFolderFile, options: .atomic)', self.shared)

class UpgradeFromLegacyAutoShare(unittest.TestCase):
    """James, build 311: an upgraded install carrying the OLD build's auto-created Documents share must never
    ask for Documents at startup. Source wiring; the native runner proves behaviour with the old build's file."""
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / 'App/main.swift').read_text()
        cls.host = (ROOT / 'Host/main.swift').read_text()
        cls.shared = (ROOT / 'Shared/Shared.swift').read_text()
        cls.removal = (ROOT / 'App/WizardRemoval.swift').read_text()

    def test_upgrade_with_legacy_default_share_does_not_touch_documents(self):
        boot = body(self.host, 'func addFilesShare(to c: VZVirtualMachineConfiguration)')
        self.assertIn('WizardShared.activeSharedFolder', boot)
        self.assertNotIn('WizardShared.filesFolder', boot)
        self.assertNotIn('defaultFilesFolder', boot)
        # The only create/mount in the whole Host must live behind the single accessor.
        self.assertEqual(self.host.count('VZSharedDirectory(url: folder'), 1)
        self.assertEqual(self.host.count('FileManager.default.createDirectory(at: folder'), 1)
        self.assertNotIn('WizardShared.filesFolder', self.host)
        self.assertNotIn('defaultFilesFolder', self.host)
        decision = self.shared[self.shared.index('files-share-decision begin'):self.shared.index('files-share-decision end')]
        accessor = body(decision, 'static var activeSharedFolder: URL?')
        self.assertIn('isLegacyAutoShare', accessor)
        for forbidden in ['fileExists', 'createDirectory', 'resolvingSymlinks', 'attributesOfItem', 'contentsOfDirectory', 'standardizedFileURL']:
            self.assertNotIn(forbidden, decision.replace('try FileManager.default.createDirectory(at: supportDir', ''),
                             'the legacy check must be string-only so it cannot trigger TCC: ' + forbidden)

    def test_explicit_share_is_honored_on_relaunch(self):
        self.assertIn('"explicit": true', body(self.shared, 'static func setFilesFolder(_ url: URL)'))
        self.assertIn('o["explicit"] as? Bool == true', self.shared)
        self.assertIn('!explicit &&', body(self.shared, 'static func isLegacyAutoShare'))

    def test_every_startup_reader_uses_the_single_accessor(self):
        self.assertIn('if let f = WizardShared.activeSharedFolder { NSWorkspace.shared.open(f) }', self.app)
        self.assertNotIn('WizardShared.filesFolder', body(self.app, 'func showFolderBlocked()'))
        self.assertNotIn('WizardShared.filesFolder', body(self.app, 'func begin()'))
        raw_users = [line.strip() for line in self.app.splitlines() if 'WizardShared.filesFolder' in line]
        # Raw saved value is for display only (QA state JSON path string); never opened or mounted.
        self.assertEqual(raw_users, ['"selectedFilesFolder": WizardShared.filesFolder?.path ?? "",'])

    def test_removal_keeps_raw_share_for_protection_only_on_user_action(self):
        self.assertIn('WizardShared.filesFolder', self.removal)   # removal protection must see the raw saved share
        self.assertIn('func show(startFresh: Bool)', self.removal)
        self.assertNotIn('makePlan(', body(self.app, 'func begin()'))

    def test_shared_files_folder_json_is_never_rewritten_outside_setFilesFolder(self):
        self.assertEqual(self.shared.count('.write(to: filesFolderFile'), 1)
        for text in (self.app, self.host):
            self.assertNotIn('filesFolderFile', text.replace('let saved = WizardShared.filesFolderFile', ''))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args, rest = parser.parse_known_args()
    ROOT = args.source_root
    unittest.main(argv=[sys.argv[0]] + rest)
