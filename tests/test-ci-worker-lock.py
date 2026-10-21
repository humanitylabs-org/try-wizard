#!/usr/bin/env python3
"""Fast scheduling contracts; run directly on Linux or macOS."""

import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

WRAPPER = Path(__file__).resolve().parents[1] / "scripts/ci-with-worker-lock.py"


class WorkerLockTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.lock = Path(self.scratch.name) / "worker.lock"
        self.env = {**os.environ, "WIZARD_CI_WORKER_LOCK": str(self.lock),
                    "WIZARD_CI_LOCK_WAIT_SECONDS": "0"}

    def run_child(self, code, **changes):
        return subprocess.run([sys.executable, str(WRAPPER), sys.executable, "-c", code],
                              env={**self.env, **changes}, capture_output=True, text=True,
                              timeout=5)

    def test_command_runs_and_preserves_exit_code(self):
        result = self.run_child("print('child ran'); raise SystemExit(7)")
        self.assertEqual(result.returncode, 7)
        self.assertIn("child ran", result.stdout)

    def test_occupied_lock_times_out_without_running_command(self):
        with self.lock.open("a+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_child("print('child ran')")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out", result.stderr)
        self.assertNotIn("child ran", result.stdout)

    def test_child_holds_lock_and_wrapper_releases_after_exit(self):
        result = self.run_child("""import fcntl, os
with open(os.environ['WIZARD_CI_WORKER_LOCK'], 'a+') as probe:
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('locked during child')
    else:
        raise SystemExit('lock was not held')
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("locked during child", result.stdout)
        with self.lock.open("a+") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_missing_lock_fails_closed(self):
        result = self.run_child("print('child ran')", WIZARD_CI_WORKER_LOCK="")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("child ran", result.stdout)

    def test_wait_cannot_exceed_bound(self):
        result = self.run_child("print('child ran')", WIZARD_CI_LOCK_WAIT_SECONDS="901")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("child ran", result.stdout)

    def test_lock_file_not_truncated_or_replaced(self):
        self.lock.write_text("existing worker metadata\n")
        inode = self.lock.stat().st_ino
        result = self.run_child("pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lock.stat().st_ino, inode)
        self.assertEqual(self.lock.read_text(), "existing worker metadata\n")


if __name__ == "__main__":
    unittest.main()
