#!/usr/bin/env python3
"""Wizard for Mac tells the page about its own updates (try-wizard#126), behind the off-by-default AppUpdates switch.

The rules (phases, the status object, the aiwizards.com-only download pages, the remembered new-download release,
the install refusals) are in Shared/AppUpdateStatus.swift and tested by Tests/AppUpdateStatus (swift test). The
release tooling's manualBelow is tested in test_release_workflow.py. This checks the wiring, and that with the switch
off nothing changes: no updates.* methods, no events, the bar and the information-only text as before.
"""
import re
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
ROOT = MAC.parents[1]


def block(src, start, end):
    a = src.index(start)
    return src[a:src.index(end, a + len(start))]


class AppUpdatesWiring(unittest.TestCase):
    def setUp(self):
        self.main = (MAC / 'App/main.swift').read_text()
        self.updater = (MAC / 'App/WizardUpdater.swift').read_text()
        self.rule = (MAC / 'Shared/AppUpdateStatus.swift').read_text()

    def test_switch_is_off_by_default_and_documented(self):
        switch = block(self.main, 'enum WizardAppUpdates {', '\n}\n')
        self.assertIn('static let key = "AppUpdates"', switch)
        self.assertIn('UserDefaults.standard.bool(forKey: key)', switch)
        self.assertIn('defaults write org.humanitylabs.wizard.mvp AppUpdates -bool YES', self.main)

    def test_bridge_methods_exist_only_with_the_switch_on(self):
        self.assertEqual(self.main.count('register("updates.")'), 1)
        gate = block(self.main, '        if WizardAppUpdates.isOn {\n            NativeBridge.shared.register("updates.")',
                     '        dragView.owner = self')
        for method in ('updates.status', 'updates.check', 'updates.install', 'updates.download'):
            self.assertIn(f'case "{method}"', gate)
        self.assertIn('WizardUpdater.shared.onStatus = ', gate)
        self.assertEqual(self.main.count('WizardUpdater.shared.onStatus'), 1)
        # Every bridge method goes through NativeBridge's one admission (trusted main frame, document generation).
        bridge = block(self.main, 'final class NativeBridge', '// MARK: - Local voice presentation')
        self.assertIn('owner?.allowsNative(message.frameInfo) == true', bridge)
        self.assertIn('guard admitted else { return }', bridge)

    def test_events_reach_only_the_trusted_main_document(self):
        send = block(self.main, '    func sendAppUpdate(', '\n    }\n')
        self.assertIn('guard WizardAppUpdates.isOn, isTrustedDocument else { return }', send)
        self.assertIn('arguments: ["name": WizardAppUpdateStatus.event, "detail": status], in: nil, in: .page', send)
        self.assertIn('static let event = "wizard:app-update"', self.rule)
        publish = block(self.updater, '    private func publishStatus() {', '\n    }\n')
        self.assertIn('guard WizardAppUpdates.isOn else { return }', publish)
        show = block(self.updater, '    private func show(_ state: String, _ text: String', '    var snapshot:')
        self.assertIn('publishStatus()', show)

    def test_switch_off_keeps_the_information_only_bar(self):
        found = block(self.updater, '    func showUpdateFound(', '    func showUpdateReleaseNotes(')
        self.assertIn('if item.isInformationOnlyUpdate, WizardAppUpdates.isOn { rememberManual(', found)
        self.assertIn('show("unavailable", "Update available but cannot be downloaded from this feed"); reply(.dismiss)', found)
        self.assertLess(found.index('WizardAppUpdates.isOn { rememberManual('), found.index('show("unavailable"'))
        start = block(self.updater, '    func start() {', '    /// Called before *every* local boot')
        self.assertIn('if WizardAppUpdates.isOn { loadManual() }', start)
        # The remembered release (and so the Download button) can only come from the switch-on paths.
        self.assertEqual(len(re.findall(r'\bmanual = record\b', self.updater)), 2)
        self.assertEqual(self.updater.count('rememberManual('), 2)   # its definition and the one switch-on call
        self.assertEqual(self.updater.count('loadManual()'), 2)

    def test_install_uses_the_bars_path_and_download_only_aiwizards(self):
        install = block(self.updater, '    func installFromPage()', '\n    }\n')
        self.assertIn('WizardAppUpdateStatus.installRefusal(', install)
        self.assertIn('recording: isRecording(), work: qaBusy', install)
        self.assertIn('updateAndRestart()', install)
        opener = block(self.updater, '    func openManualDownload()', '\n    }\n')
        self.assertIn('WizardAppUpdateStatus.allowsDownload(page)', opener)
        self.assertIn('NSWorkspace.shared.open(url)', opener)
        self.assertEqual(self.updater.count('NSWorkspace.shared.open('), 1)
        bar = block(self.updater, '    @objc func updateAndRestart() {', '\n    }\n')
        self.assertIn('if phase == "manual", manual != nil, ready == nil { _ = openManualDownload(); return }', bar)
        self.assertIn('static let allowedHosts: Set<String> = ["www.aiwizards.com", "downloads.aiwizards.com"]', self.rule)

    def test_the_rule_is_built_into_the_app_and_tested(self):
        build = (MAC / 'build.sh').read_text()
        app_line = next(line for line in build.splitlines() if 'App/main.swift' in line and '-o "$APP/Contents/MacOS/Wizard"' in line)
        self.assertIn('Shared/AppUpdateStatus.swift', app_line)
        pkg = (MAC / 'Package.swift').read_text()
        self.assertIn('sources: ["AppUpdateStatus.swift"]', pkg)
        self.assertIn('path: "Tests/AppUpdateStatus"', pkg)
        self.assertTrue((MAC / 'Tests/AppUpdateStatus/AppUpdateStatusTests.swift').exists())
        self.assertIn('next/mac/Tests/test_app_updates.py', (ROOT / 'Makefile').read_text())


if __name__ == '__main__':
    unittest.main()
