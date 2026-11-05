#!/usr/bin/env python3
"""Source-wiring regressions; NOT AppKit execution or real GUI/VM proof.

The native companion run_host_launch_checks.py executes the extracted production
HostControl with fake Workspace/process inventory, without launching an app.
"""
from pathlib import Path
import argparse
import unittest

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ROOT = DEFAULT_ROOT


def body(text, declaration):
    start = text.index(declaration)
    opening = start
    parentheses = 0
    while True:
        char = text[opening]
        parentheses += (char == '(') - (char == ')')
        if char == '{' and parentheses == 0:
            break
        opening += 1
    depth = 1
    at = opening + 1
    while depth:
        depth += (text[at] == '{') - (text[at] == '}')
        at += 1
    return text[opening + 1:at - 1]


class HostLaunchWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'App/main.swift').read_text()
        cls.host = body(cls.source, 'enum HostControl {')
        cls.ensure = body(cls.host, 'static func ensureRunning(')
        cls.connect = body(cls.source, 'func connectLocal()')

    def test_workspace_launch_error_has_caller_completion(self):
        self.assertIn('static func ensureRunning(completion:', self.host,
                      'Workspace launch errors must reach the selected-local caller, not NSLog alone')
        self.assertIn('finish("Wizard couldn\'t start its local Host:', self.ensure)
        self.assertIn('completion(error)', self.host)

    def test_foreign_runner_and_maintenance_return_errors(self):
        self.assertIn('finish("Wizard is preparing', self.ensure)
        self.assertIn('finish("Another copy of Wizard', self.ensure)

    def test_workspace_returned_identity_is_checked(self):
        self.assertIn('app?.bundleURL?.resolvingSymlinksInPath() == embeddedHostURL.resolvingSymlinksInPath()', self.ensure)

    def test_connect_handles_launch_error_before_sending_start(self):
        self.assertIn('HostControl.ensureRunning {', self.connect)
        callback = body(self.connect, 'HostControl.ensureRunning {')
        self.assertIn('if let error', callback)
        self.assertIn('failed = true', callback)
        self.assertIn('self.showOverlay("Wizard OS didn\'t start", error', callback)
        self.assertIn('self.voiceConnectionGeneration == generation', callback)
        self.assertGreater(callback.index('HostControl.send("start")'), callback.index('if let error'))
        self.assertEqual(self.connect.count('HostControl.send("start")'), 1)
        self.assertIn('HostControl.waitForLocalWizard(', callback)
        self.assertIn('120 - Date().timeIntervalSince(started)', callback)
        self.assertIn('guard !completed else { return }', self.ensure)
        self.assertIn('DispatchQueue.main.asyncAfter(deadline: .now() + 120)', self.ensure)

    def test_launch_failure_persists_in_logs_not_host_status(self):
        self.assertIn('app-startup.log', self.host)
        self.assertNotIn('statusFile', self.ensure)
        # Installation must use the same checked launch path, not broadcast first.
        install = body(self.source, 'func installOnThisMac()')
        self.assertNotIn('HostControl.send("start")', install)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=DEFAULT_ROOT)
    args, rest = parser.parse_known_args()
    ROOT = args.source_root
    unittest.main(argv=[__file__, *rest])
