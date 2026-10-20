"""Next-release source contract only: this does not build a guest or prove delivery."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NextReleaseBackupPin(unittest.TestCase):
    def test_payload_and_candidate_use_the_backup_engine(self):
        candidate = json.loads((ROOT / 'mac/release-next.json').read_text())
        module = ast.parse((ROOT / 'guest/build-runtime-payload.py').read_text())
        pins = next(ast.literal_eval(node.value) for node in module.body
                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PINS' for t in node.targets))
        self.assertEqual(candidate['wam'], '850cfe3252576b3a9ae9bea54c4fedd173691443')
        self.assertEqual(pins['wam'], candidate['wam'])
        self.assertEqual(candidate['channel'], 'candidate-only')
        self.assertEqual(candidate['guestImageRebuild'], 'not-authorized')

    def test_native_build_preserves_updater_and_backup_inputs(self):
        build = (ROOT / 'mac/build.sh').read_text()
        for source in ('Shared/BackupContract.swift', 'App/WizardBackup.swift', 'App/WizardUpdater.swift',
                       'Shared/UpdateContract.swift', 'Shared/DiskIdentity.swift', 'Shared/GuestPatchCommand.swift',
                       'Shared/HostTermination.swift'):
            self.assertIn(source, build)
        app = (ROOT / 'mac/App/main.swift').read_text()
        self.assertIn('backup.install(in: appMenu)', app)
        self.assertIn('#selector(WizardUpdater.checkForUpdates(_:))', app)


if __name__ == '__main__':
    unittest.main()
