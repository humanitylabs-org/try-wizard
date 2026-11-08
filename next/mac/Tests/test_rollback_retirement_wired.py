#!/usr/bin/env python3
"""The update rollback disk is retired after a confirmed upgrade, for everyone (issue #31).

Owner report: after 0.6.1 -> 0.7.0, updates/previous-disk.img stayed forever and grew to 6.4 GB.
The rule itself is tested in Tests/RollbackRetirement (swift test). CI does not compile the App
target, so this checks the source wiring: the cleanup is built into the app, runs on launch and
after a successful activation, and has no off switch.
"""
import re
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


class RollbackRetirementWiredTests(unittest.TestCase):
    def test_app_build_compiles_the_cleanup(self):
        build = (MAC / 'build.sh').read_text()
        app_line = next(l for l in build.splitlines() if 'App/main.swift' in l and 'MacOS/Wizard"' in l)
        self.assertIn('Shared/RollbackRetirement.swift', app_line)
        self.assertIn('App/WizardRollbackCleanup.swift', app_line)

    def test_cleanup_runs_on_launch_and_after_activation(self):
        src = (MAC / 'App/WizardUpdater.swift').read_text()
        self.assertRegex(src, r'if journal\["phase"\] as\? String == "guest-activated" \{ WizardRollbackCleanup\.start\(\) \}')
        self.assertRegex(src, r'if error == nil \{ WizardRollbackCleanup\.start\(\) \}')

    def test_cleanup_is_on_for_everyone(self):
        src = (MAC / 'App/WizardRollbackCleanup.swift').read_text()
        self.assertNotIn('UserDefaults', src)
        self.assertNotIn('RetireRollbackDisk', src)
        start = src[src.find('static func start()'):src.find('private static func check(')]
        self.assertRegex(start, r'guard !scheduled, FileManager\.default\.fileExists')

    def test_rule_keeps_the_disk_outside_guest_activated(self):
        rule = (MAC / 'Shared/RollbackRetirement.swift').read_text()
        self.assertRegex(rule, r'"guest-activated"')
        self.assertTrue(re.search(r'24 \* 60 \* 60|86_?400', rule), 'the 24 h grace period must stay')


if __name__ == '__main__':
    unittest.main()
