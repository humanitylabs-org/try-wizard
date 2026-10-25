import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('factory_probe', HERE / 'probe-factory.py')
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class FactoryProbeTests(unittest.TestCase):
    def test_default_is_read_only(self):
        row = subprocess.run([sys.executable, HERE / 'probe-factory.py', '--stage-root', '/nonexistent'], check=True, capture_output=True, text=True)
        receipt = json.loads(row.stdout)
        self.assertIs(receipt['buildStarted'], False)
        self.assertIs(receipt['publishing'], False)

    def test_external_snapshot_scope_refuses_owner_paths(self):
        with patch.object(probe.sys, 'platform', 'darwin'), patch.dict(probe.os.environ, {'THALES_MEDIA': str(HERE.parents[4])}):
            with self.assertRaisesRegex(AssertionError, 'diagnostic snapshot only'):
                probe.assert_owned_stage(HERE)

    def test_non_mac_is_refused(self):
        with patch.object(probe.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(AssertionError, 'Thales worker only'):
                probe.assert_owned_stage(HERE)

    def offline(self, code=0, machine=b'', source=b'fixture-pin\n', forbidden=b'File not found'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disk = root / 'data/os/disk.img'
            disk.parent.mkdir(parents=True)
            answers = [types.SimpleNamespace(returncode=code, stdout='fsck', stderr=''),
                       types.SimpleNamespace(stdout=machine), types.SimpleNamespace(stdout=source),
                       types.SimpleNamespace(stderr=forbidden), types.SimpleNamespace(stderr=forbidden)]
            with patch.object(probe.subprocess, 'run', side_effect=answers):
                probe.offline_identity(types.SimpleNamespace(E2='/test/'), disk, {'finalPins': {'wam': 'fixture-pin'}})

    def test_real_pack_identity_contract_fixture(self):
        self.offline()

    def test_fsck_failure_is_not_swallowed(self):
        with self.assertRaises(AssertionError):
            self.offline(code=4)

    def test_machine_id_failure_is_not_swallowed(self):
        with self.assertRaisesRegex(AssertionError, 'machine identity'):
            self.offline(machine=b'used-id')

    def test_source_mismatch_is_not_swallowed(self):
        with self.assertRaisesRegex(AssertionError, 'WAM source'):
            self.offline(source=b'wrong-pin\n')

    def test_forbidden_identity_is_not_swallowed(self):
        with self.assertRaisesRegex(AssertionError, 'identity survived'):
            self.offline(forbidden=b'exists')


if __name__ == '__main__':
    unittest.main()
