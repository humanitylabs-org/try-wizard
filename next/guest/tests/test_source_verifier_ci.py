"""Control-plane contracts for the frozen-source verifier, no Docker required."""
import re
import runpy
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

RELEASE = Path(__file__).resolve().parents[1] / 'releases/mac-launch-20261027'
sys.path.insert(0, str(RELEASE))
VERIFIER = runpy.run_path(str(RELEASE / 'verify-sources-v5.py'))
SCRIPT = VERIFIER['linux_script']()


class SourceVerifierCI(unittest.TestCase):
    def test_managed_interpreter_regression_runs_on_selected_native_source(self):
        source = (RELEASE / 'verify-sources-v5.py').read_text()
        self.assertIn("('managed-interpreters',['-m','unittest','discover','-s','next/guest/tests','-p','test_managed_interpreters.py'])", source)

    def test_overlay_mode_regression_runs_on_selected_native_source(self):
        source = (RELEASE / 'verify-sources-v5.py').read_text()
        self.assertIn("('overlay-tool-modes',['-m','unittest','discover','-s','next/guest/tests','-p','test_overlay_tool_modes.py'])", source)

    def test_rendered_shell_is_valid(self):
        self.assertIsNotNone(shutil.which('bash'))
        subprocess.run(['bash', '-n'], input=SCRIPT, text=True, check=True)

    def test_python_is_independently_digest_pinned(self):
        self.assertRegex(VERIFIER['PYTHON_IMAGE'], r'^python@sha256:[a-f0-9]{64}$')
        self.assertIn('cp -a /opt/ci-python/. /usr/local/; ldconfig', SCRIPT)
        self.assertIn('python3 -m venv /work/venv', SCRIPT)

    def test_checkout_owned_by_ci_user_with_real_commits(self):
        self.assertIn('chown -R node:node /work/src /work/logs', SCRIPT)
        self.assertIn('git config --system user.name', SCRIPT)
        self.assertIn('git config --system user.email', SCRIPT)
        self.assertIn('git init -q -b main', SCRIPT)
        self.assertIn('git commit -qm "Frozen source export"', SCRIPT)
        self.assertNotIn('safe.directory', SCRIPT)
        self.assertIn('umask 022', SCRIPT)

    def test_root_and_unprivileged_suites_remain_separate(self):
        root_suite = SCRIPT.index('python3 tests/managed_recovery_test.py')
        user_suite = SCRIPT.index("bash <<'CI_SUITES'")
        self.assertLess(root_suite, user_suite)
        self.assertIn('sudo -H -u node env TMPDIR=/work/t', SCRIPT)
        self.assertIn('groupadd -f docker', SCRIPT)
        self.assertIn('python3-yaml', SCRIPT)

    def test_required_service_package_suites_are_not_omitted(self):
        for token in ['node scripts/test-hermes-import.mjs', 'npx vitest run',
                      'tests/session-text-search-worker.node.mjs', 'tests/agent-archive-list.node.mjs',
                      'tests/chat-photo-*.node.mjs', 'tests/chats-install-e2e.node.mjs',
                      'tests/test_chat_photo_reader.py', 'tests/test_standard_chats_relay.py',
                      'qa/agent-parity/fixture.test.mjs', 'REQUIRE_ROLLBACK_REHEARSAL=1']:
            self.assertIn(token, SCRIPT)
        self.assertIn('859c548d43081a5e28a37680e796d07041971601', SCRIPT)
        self.assertNotIn('--ignore-scripts', SCRIPT)

    def test_full_existing_suites_without_selection_or_test_edits(self):
        self.assertIn('node --test tests/*.test.mjs', SCRIPT)
        self.assertIn('/work/venv/bin/python -m pytest -q -rs >', SCRIPT)
        self.assertIn('/work/venv/bin/python tests/test_portable_paths.py', SCRIPT)
        self.assertIn('node --test tests/runtipi-open.test.mjs', SCRIPT)
        self.assertNotRegex(SCRIPT, r'--(?:deselect|ignore|exclude)|pytest[^\n]*\s-(?:k|m)\s')
        self.assertNotRegex(SCRIPT, r'(?:sed|patch|perl)\b[^\n]*tests/')
        self.assertIn('ruamel.yaml==0.19.1', SCRIPT)
        self.assertTrue(SCRIPT.rstrip().endswith('exit $rc'))


if __name__ == '__main__':
    unittest.main()
