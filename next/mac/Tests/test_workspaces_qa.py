#!/usr/bin/env python3
"""QA harness regression checks; fake compiler is packaging proof, not a Mac build."""
import ast
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceQARegressionTests(unittest.TestCase):
    def test_qa_bundle_contains_exact_required_brand_assets(self):
        with tempfile.TemporaryDirectory(prefix='workspace-qa-') as tmp:
            tmp = Path(tmp)
            tools = tmp / 'bin'
            tools.mkdir()
            # Exercise the actual build script's packaging on any host. No Swift
            # compilation, framework validation or native acceptance is claimed.
            for name, body in {
                'uname': '#!/bin/sh\nprintf "Darwin\\n"\n',
                'xcrun': '#!/bin/sh\nexit 0\n',
                'ditto': '#!/bin/sh\nmkdir -p "$2"\n',
            }.items():
                path = tools / name
                path.write_text(body)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'], SPARKLE_DIR=str(tmp / 'sparkle'))
            out = tmp / 'build'
            subprocess.run(['bash', str(ROOT / 'tools/build-workspaces-qa.sh'), str(out)],
                           env=env, check=True, capture_output=True)
            resources = out / 'Wizard Switcher QA.app/Contents/Resources'
            for name in ['wizard-mark-purple.png', 'wizard-mark-white.png']:
                self.assertEqual((resources / name).read_bytes(), (ROOT / 'assets/brand' / name).read_bytes())

    def test_native_wait_reports_exited_app_without_timing_out(self):
        tree = ast.parse((ROOT / 'qa-workspaces.py').read_text())
        functions: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'wait']
        namespace = {'time': __import__('time'), 'proc': Mock(), 'logs': []}
        namespace['proc'].poll.return_value = -5
        namespace['proc'].returncode = -5
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<qa-wait>', 'exec'), namespace)
        with self.assertRaisesRegex(AssertionError, 'exited.*-5'):
            namespace['wait'](lambda: False, timeout=.01)


if __name__ == '__main__':
    unittest.main()
