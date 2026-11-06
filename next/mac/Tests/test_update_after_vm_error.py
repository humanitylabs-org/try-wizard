#!/usr/bin/env python3
"""A failed local Wizard OS must not block a Mac app update.

Owner report (6 Nov 2026): the bar said "Wizard OS is starting or stopping" and Update and restart did nothing,
forever. The local VM was in its "error" state, which the updater treated like a start/stop in progress.
The App can request recovery from an error, but the Host bypasses maintenance
only when the actual VM is absent or stopped; a live errored VM keeps admission.
These source contracts do not establish native shutdown or notice-bar geometry.
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

    def test_host_error_bypass_requires_no_live_vm(self):
        src = (MAC / 'Host/main.swift').read_text()
        self.assertRegex(src, r'if self\.vm\.state == \.stopped \|\| self\.vm\.state == \.notInstalled \|\| \(self\.vm\.state == \.error && self\.vm\.canTerminateWithoutStopping\) \|\|[^\n]*stopWhenIdle\(nil\)')

    def test_later_width_preference_yields_to_required_intrinsic_sizing(self):
        src = (MAC / 'App/WizardUpdater.swift').read_text()
        self.assertIn('let laterWidth = later.widthAnchor.constraint(lessThanOrEqualToConstant: 110)', src)
        self.assertIn('laterWidth.priority = NSLayoutConstraint.Priority(999)', src)
        self.assertLess(src.index('laterWidth.priority ='), src.index('laterWidth.isActive = true'))


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
