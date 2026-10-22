#!/usr/bin/env python3
"""Keep the HTTP backup tests runnable on a clean, externally managed Mac Python."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackupDependenciesTests(unittest.TestCase):
    def test_dependency_is_declared(self):
        requirements = (ROOT / "next/guest/tests/requirements.txt").read_text()
        self.assertIn("aiohttp>=3.13.3,<4", requirements)

    def test_ci_installs_before_running_tests(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertLess(workflow.index("pip install -r next/guest/tests/requirements.txt"),
                        workflow.index("name: Run test suite"))

    def test_ci_uses_isolated_python_and_exports_it(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn('python3 -m venv "$RUNNER_TEMP/backup-tests-${GITHUB_RUN_ID}"', workflow)
        self.assertIn('"$RUNNER_TEMP/backup-tests-${GITHUB_RUN_ID}/bin/python" -m pip install', workflow)
        self.assertIn('"$RUNNER_TEMP/backup-tests-${GITHUB_RUN_ID}/bin" >> "$GITHUB_PATH"', workflow)
        self.assertNotIn("--break-system-packages", workflow)


if __name__ == "__main__":
    unittest.main()
