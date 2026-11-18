#!/usr/bin/env python3
"""Every workflow runs on GitHub-hosted runners: the wizard-os#680 security review needs the self-hosted runners
(the team Mac and the forum box) unregistered before the real Sparkle key goes into GitHub (try-wizard#113)."""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / '.github/workflows'


class NoSelfHostedRunners(unittest.TestCase):
    def test_workflows_exist(self):
        self.assertTrue(list(WORKFLOWS.glob('*.yml')))

    def test_no_workflow_targets_a_self_hosted_runner(self):
        for path in sorted(WORKFLOWS.glob('*.y*ml')):
            # Comments may explain the history; only the workflow's YAML counts.
            text = '\n'.join(line for line in path.read_text().splitlines() if not line.lstrip().startswith('#'))
            with self.subTest(workflow=path.name):
                self.assertNotIn('self-hosted', text)
                # A runs-on passed through to a reusable workflow must not name a custom runner label either.
                for value in re.findall(r'(?m)^\s*runs-on:\s*(.+)$', text):
                    self.assertNotRegex(value, r'forum|thales|try-wizard|ARM64|X64')

    def test_self_hosted_fallback_is_gone(self):
        self.assertFalse((WORKFLOWS / 'ci-self-hosted.yml').exists())


if __name__ == '__main__':
    unittest.main()
