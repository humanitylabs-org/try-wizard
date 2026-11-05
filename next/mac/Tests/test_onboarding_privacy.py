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
        self.assertIn('if let folder = WizardShared.filesFolder', self.host)
        self.assertIn('VZSingleDirectoryShare(directory: VZSharedDirectory(url: folder, readOnly: false))', self.host)
        upload = body(self.app, 'func webView(_ webView: WKWebView, runOpenPanelWith')
        self.assertIn('panel.beginSheetModal', upload)
        self.assertNotIn('setFilesFolder', upload)
        self.assertIn('try d.write(to: filesFolderFile, options: .atomic)', self.shared)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args, rest = parser.parse_known_args()
    ROOT = args.source_root
    unittest.main(argv=[sys.argv[0]] + rest)
