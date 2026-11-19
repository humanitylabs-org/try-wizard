#!/usr/bin/env python3
"""try-wizard#127: after a Mac app update the new app brings up a Host of its own build, or says what to do.

Updating from build 311 to 312 left the window on the logo with "New Host health not confirmed — previous app
remains available in updates/previous.app": the app only waited for the new Host, never replaced an old one,
and its banner named an internal path with no working action. The decisions live in Shared/HostHandover.swift
(XCTest fixtures in Tests/HostHandover run on macOS CI); this checks the wiring that runs everywhere.
"""
import re
import sys
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
UPDATER = (MAC / 'App/WizardUpdater.swift').read_text()
MAIN = (MAC / 'App/main.swift').read_text()


class HostHandoverWiring(unittest.TestCase):
    def test_banners_name_no_internal_paths(self):
        for lit in re.findall(r'show\("[^"]*", "((?:[^"\\]|\\.)*)"', UPDATER):
            self.assertNotIn('previous.app', lit)
            self.assertNotIn('updates/', lit)
        self.assertNotIn('health not confirmed', UPDATER)

    def test_updater_drives_the_handover_and_never_force_kills(self):
        self.assertIn('handover.next(status: WizardUpdate.json(WizardShared.statusFile)', UPDATER)
        self.assertIn('NSRunningApplication(processIdentifier: pid)?.terminate()', UPDATER)
        for forced in ('forceTerminate', 'SIGKILL', 'kill(pid, 9)', 'SIGTERM'):
            self.assertNotIn(forced, UPDATER)
        self.assertIn('confirmNativeHost(build: current)', UPDATER)

    def test_retry_on_the_bar_and_in_the_window_restarts_the_handover(self):
        self.assertIn('if phase == "host-recovery" { _ = retryHostHandover(); return }', UPDATER)
        self.assertRegex(UPDATER, r'case \.stalled:\s*\n\s*show\("host-recovery", WizardHostHandover\.troubleText, retry: true\)')
        self.assertIn('@objc func retry() { WizardUpdater.shared.retryHostHandover(); begin() }', MAIN)

    def test_window_shows_the_recovery_instead_of_an_empty_loading_bar(self):
        hook = MAIN[MAIN.index('WizardUpdater.shared.onHostHandover = {'):]
        hook = hook[:hook.index('WizardUpdater.shared.onActivationStatus')]
        self.assertIn('spinning: false', hook)
        self.assertIn('#selector(WizardWindowController.retry)', hook)
        self.assertIn('#selector(WizardWindowController.quitWizard)', hook)
        self.assertIn('controller.begin()', hook)

    def test_window_does_not_race_the_updater_for_the_host(self):
        connect = MAIN[MAIN.index('    func connectLocal() {'):MAIN.index('    func load(_ url: URL) {')]
        self.assertRegex(connect, r'if !WizardUpdater\.shared\.handoverActive \{\s*\n\s*HostControl\.ensureRunning\(\)\s*\n\s*HostControl\.send\("start"\)')

    def test_handover_is_compiled_into_the_app_and_tested(self):
        self.assertIn('Shared/HostHandover.swift App/WizardBackup.swift', (MAC / 'build.sh').read_text())
        self.assertIn('Tests/HostHandover', (MAC / 'Package.swift').read_text())


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
