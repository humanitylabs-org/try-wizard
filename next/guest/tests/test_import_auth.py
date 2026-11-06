"""Exercise the production auth helper with synthetic bytes, without Hermes.

Set IMPORTER_SCRIPT to run these identical regressions against another revision.
All fixtures live under the caller's scratch TMPDIR.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(os.environ.get(
    "IMPORTER_SCRIPT",
    str(Path(__file__).parents[1] / "overlay/opt/wizard/bin/wizard-import-hermes"),
))
loader = importlib.machinery.SourceFileLoader("importer_auth", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


class KeepWizardAuth(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"])
        self.addCleanup(self.home.cleanup)
        self.data = Path(self.home.name)
        self.settings = mock.patch.multiple(m, DATA=self.data, UID=os.getuid(), GID=os.getgid())
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.auth = self.data / "auth.json"
        self.predictable = self.data / "auth.json.wizard-import"
        self.wizard = b'{"synthetic_wizard": "fixture-only"}\n\x00'
        self.old = b'{"synthetic_imported": true}'

    def test_absent_wizard_auth_unlinks_imported_auth(self):
        self.auth.write_bytes(self.old)
        self.assertFalse(m.keep_wizard_auth(None))
        self.assertFalse(self.auth.exists())
        self.assertFalse(m.keep_wizard_auth(None))
        self.assertEqual(list(self.data.iterdir()), [])

    def test_normal_bytes_mode_and_owner(self):
        self.auth.write_bytes(self.old)
        self.assertTrue(m.keep_wizard_auth(self.wizard))
        self.assertEqual(self.auth.read_bytes(), self.wizard)
        info = self.auth.stat()
        self.assertEqual(info.st_mode & 0o777, 0o600)
        self.assertEqual((info.st_uid, info.st_gid), (os.getuid(), os.getgid()))
        self.assertEqual(set(self.data.iterdir()), {self.auth})

    def test_preexisting_predictable_644_file_is_not_reused(self):
        self.predictable.write_bytes(b"unrelated fixture")
        self.predictable.chmod(0o644)
        self.assertTrue(m.keep_wizard_auth(self.wizard))
        self.assertEqual(self.auth.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.auth.read_bytes(), self.wizard)
        self.assertEqual(self.predictable.read_bytes(), b"unrelated fixture")
        self.assertEqual(self.predictable.stat().st_mode & 0o777, 0o644)
        self.assertEqual(set(self.data.iterdir()), {self.auth, self.predictable})

    def test_predictable_symlink_target_is_unmodified(self):
        target = self.data / "unrelated-target"
        target.write_bytes(b"must stay untouched")
        target.chmod(0o644)
        self.predictable.symlink_to(target)
        self.assertTrue(m.keep_wizard_auth(self.wizard))
        self.assertEqual(target.read_bytes(), b"must stay untouched")
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        self.assertTrue(self.predictable.is_symlink())
        self.assertEqual(self.auth.read_bytes(), self.wizard)
        self.assertEqual(self.auth.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(self.data.iterdir()), {self.auth, self.predictable, target})

    def test_failures_clean_temporary_file_and_preserve_old_auth(self):
        for operation in ("fdopen", "fchmod", "fchown", "replace"):
            with self.subTest(operation=operation):
                self.auth.write_bytes(self.old)
                self.auth.chmod(0o640)
                with mock.patch.object(m.os, operation, side_effect=OSError("synthetic failure")):
                    with self.assertRaises(OSError):
                        m.keep_wizard_auth(self.wizard)
                self.assertEqual(self.auth.read_bytes(), self.old)
                self.assertEqual(self.auth.stat().st_mode & 0o777, 0o640)
                self.assertEqual(set(self.data.iterdir()), {self.auth})

    def test_owner_is_set_on_private_open_descriptor_before_replace(self):
        actual_fchown = os.fchown
        observed = []

        def inspect_owner(fd, uid, gid):
            info = os.fstat(fd)
            self.assertEqual(info.st_mode & 0o777, 0o600)
            self.assertFalse(self.auth.exists())
            self.assertTrue(any(p.stat().st_ino == info.st_ino for p in self.data.iterdir()))
            observed.append((uid, gid))
            return actual_fchown(fd, uid, gid)

        with mock.patch.object(m.os, "fchown", side_effect=inspect_owner):
            self.assertTrue(m.keep_wizard_auth(self.wizard))
        self.assertEqual(observed, [(os.getuid(), os.getgid())])


if __name__ == "__main__":
    unittest.main()
