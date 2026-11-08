#!/usr/bin/env python3
"""A failed local WizardOS must not block a Mac app update.

Owner report (6 Nov 2026): the bar said "WizardOS is starting or stopping" and Update and restart did nothing,
forever. The local VM was in its "error" state, which the updater treated like a start/stop in progress.
A failed VM has no agent work to protect, so the update proceeds and the Host stops whatever is left.
"""
import re
import sys
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


class UpdateAfterVMErrorTests(unittest.TestCase):
    def test_app_lets_an_errored_local_os_update(self):
        src = (MAC / 'Shared/UpdateContract.swift').read_text()
        idle = src[src.find('static func idle('):src.find('static let maintenanceJournal')]
        self.assertRegex(idle, r'case "error": done\(nil\); return')
        self.assertNotIn('starting or stopping', idle)

    def test_host_stops_an_errored_os_without_asking_its_dead_agents(self):
        src = (MAC / 'Host/main.swift').read_text()
        self.assertRegex(src, r'if self\.vm\.state == \.stopped \|\| self\.vm\.state == \.notInstalled \|\| self\.vm\.state == \.error \|\|[^\n]*stopWhenIdle\(nil\)')

    def test_later_button_cannot_stretch_across_the_bar(self):
        src = (MAC / 'App/WizardUpdater.swift').read_text()
        self.assertRegex(src, r'later\.widthAnchor\.constraint\(lessThanOrEqualToConstant: \d+\)\.isActive = true')


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
