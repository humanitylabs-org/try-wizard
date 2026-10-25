"""Managed packaging must follow the selected stock's actual interpreter layout."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('managed_install', ROOT / 'managed-launch/install.py')
assert spec and spec.loader
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class ManagedInterpreters(unittest.TestCase):
    def exercise(self, uv):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            system = root / 'usr/bin/python3.13'
            system.parent.mkdir(parents=True)
            system.write_bytes(b'\x7fELFsystem-python');system.chmod(0o755)
            (system.parent / 'python3').symlink_to(system.name)
            binaries = [system]
            # A different version and architecture deliberately defeats fixed paths.
            target = system
            if uv:
                target = root / 'opt/uv-python/cpython-3.14.9-linux-x86_64-gnu/bin/python3.14'
                target.parent.mkdir(parents=True)
                target.write_bytes(b'\x7fELFuv-python');target.chmod(0o755)
                binaries.append(target)
            venv = root / 'opt/hermes/.venv/bin'
            venv.mkdir(parents=True)
            (venv / 'python').symlink_to(target)
            (venv / 'python3').symlink_to('python')
            (system.parent / 'python-config').write_text('not an interpreter')
            paths = install.interpreter_paths([root / 'usr/bin', root / 'opt/uv-python', venv], venv / 'python')
            self.assertEqual(paths, sorted(binaries))
            originals = {p: p.read_bytes() for p in paths}
            managed = root / 'managed'
            managed.mkdir()
            def compile_guard(argv, check):
                self.assertTrue(check)
                Path(argv[-1]).write_bytes(b'\x7fELFguard')
            with patch.object(install.os, 'getuid', return_value=0), patch.object(install.subprocess, 'run', side_effect=compile_guard):
                install.install(managed, paths)
            receipts = json.loads((managed / 'interpreters.json').read_text())
            self.assertEqual({r['path'] for r in receipts}, {str(p) for p in paths})
            for receipt in receipts:
                p = Path(receipt['path'])
                exported = managed / 'interpreter-overlay' / p.relative_to('/')
                self.assertEqual(exported.read_bytes(), b'\x7fELFguard')
                self.assertEqual(exported.stat().st_mode & 0o7777, 0o4755)
                self.assertEqual(Path(receipt['private']).read_bytes(), originals[p])
                self.assertEqual(receipt['stock_sha256'], hashlib.sha256(originals[p]).hexdigest())
            self.assertTrue((venv / 'python').is_symlink())
            self.assertEqual((venv / 'python').resolve(), target)
            self.assertEqual((managed / 'private').stat().st_mode & 0o777, 0o700)

    def test_security_stock_system_python_without_uv_tree(self):
        self.exercise(False)

    def test_versioned_uv_python_and_system_python_are_both_exported(self):
        self.exercise(True)

    def test_missing_hermes_interpreter_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(AssertionError):
                install.interpreter_paths([td], Path(td) / 'missing')

    def test_docker_final_stage_copies_discovered_guards_not_fixed_python_paths(self):
        source = (ROOT / 'managed-launch/Dockerfile').read_text()
        self.assertIn('COPY --from=compiler /opt/wizard-managed/interpreter-overlay/ /', source)
        self.assertNotIn('COPY --from=compiler /usr/bin/python', source)
        self.assertNotIn('COPY --from=compiler /opt/uv-python/', source)
        self.assertEqual(source.count('FROM ${HERMES_IMAGE}'), 2)


if __name__ == '__main__':
    unittest.main()
