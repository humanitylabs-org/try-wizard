#!/usr/bin/env python3
"""Endpoint configuration contracts; no network or native app execution."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SHELL_CASES = (
    ('wizard/scripts/update.sh.in', 'WIZARD_UPDATE_BASE', 'BASE', 'VER='),
    ('next/mac/qa-e2e-published.sh', 'WIZARD_QA_DOWNLOAD_BASE', 'B', 'AS='),
    ('next/mac/qa-mizel-view.sh', 'WIZARD_QA_BASE_URL', 'BASE', 'cd '),
    ('next/mac/qa-wizard-ux.sh', 'WIZARD_QA_BASE_URL', 'BASE', 'cd '),
    ('next/mac/qa-voice.sh', 'WIZARD_QA_BASE_URL', 'BASE', 'cd '),
)


class ConfiguredEndpoints(unittest.TestCase):
    def shell_config(self, path, variable, output, boundary, value):
        source = (ROOT / path).read_text().split(boundary, 1)[0]
        env = dict(os.environ)
        env.pop(variable, None)
        if value is not None:
            env[variable] = value
        return subprocess.run(
            ['bash', '-c', source + '\nprintf "%s" "$' + output + '"'],
            env=env, capture_output=True, text=True, check=False,
        )

    def test_shell_requires_explicit_endpoint_before_side_effects(self):
        for case in SHELL_CASES:
            for value in (None, ''):
                with self.subTest(path=case[0], value=value):
                    result = self.shell_config(*case, value)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(case[1], result.stderr)

    def test_shell_preserves_configured_origin_port_and_path(self):
        for case in SHELL_CASES:
            value = 'https://wizard.example:8443/downloads' if case[2] == 'B' or case[3] == 'VER=' else 'https://wizard.example:8443'
            for suffix in ('', '/'):
                with self.subTest(path=case[0], suffix=suffix):
                    result = self.shell_config(*case, value + suffix)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, value)

    def native_url(self, value):
        tree = ast.parse((ROOT / 'next/mac/qa-desktop-keys.py').read_text())
        assignments: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'URL' for t in node.targets)]
        self.assertEqual(len(assignments), 1)
        namespace = {'os': os}
        env = {} if value is None else {'QA_NATIVE_URL': value}
        with patch.dict(os.environ, env, clear=True):
            exec(compile(ast.Module(body=assignments, type_ignores=[]), '<config>', 'exec'), namespace)
        return namespace['URL']

    def test_native_qa_requires_explicit_url(self):
        with self.assertRaises(KeyError):
            self.native_url(None)

    def test_native_qa_missing_or_empty_url_exits_before_side_effects(self):
        for value in (None, ''):
            with self.subTest(value=value):
                env = dict(os.environ)
                env.pop('QA_NATIVE_URL', None)
                if value is not None:
                    env['QA_NATIVE_URL'] = value
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'next/mac/qa-desktop-keys.py')],
                    env=env, capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('QA_NATIVE_URL', result.stderr)
                self.assertNotIn('PermissionError', result.stderr)

    def test_native_qa_preserves_full_url(self):
        url = 'https://wizard.example:8443/wizard-os-home/desktop.html?qa=1'
        self.assertEqual(self.native_url(url), url)

    def test_shell_qa_connections_use_configured_base(self):
        for filename in ('qa-mizel-view.sh', 'qa-wizard-ux.sh', 'qa-voice.sh'):
            source = (ROOT / 'next/mac' / filename).read_text()
            connections = [line for line in source.splitlines() if './qa.sh "connect ' in line]
            self.assertTrue(connections, filename)
            for line in connections:
                self.assertIn('./qa.sh "connect $BASE/', line, filename)


if __name__ == '__main__':
    unittest.main()
