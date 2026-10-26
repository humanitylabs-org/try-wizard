#!/usr/bin/env python3
"""Protect the native backup feature when composing successor releases."""
from pathlib import Path
import unittest

MAC=Path(__file__).resolve().parents[1]/'next/mac'

class BackupReleaseParityTests(unittest.TestCase):
    def test_successor_build_keeps_native_backup_contract_controller_and_frameworks(self):
        build=(MAC/'build.sh').read_text()
        for value in ('Shared/BackupContract.swift','App/WizardBackup.swift',
                      '-framework Security','-framework UniformTypeIdentifiers','App/UpdateArtifact.swift'):
            self.assertIn(value,build)

    def test_successor_app_installs_backup_menu_before_check_for_updates(self):
        source=(MAC/'App/main.swift').read_text()
        self.assertIn('var backup: WizardBackupController?',source)
        self.assertLess(source.index('backup.install(in: appMenu)'),source.index('appMenu.addItem(withTitle: "Check for Updates…"'))
        for value in ('backup.isLocal = { Store.active?.kind == .thisMac }',
                      'backup.wizardName = { Store.active?.name ?? "Wizard" }',
                      'backup.didRestore = { [weak self] in self?.controller.begin() }', 'self.backup = backup'):
            self.assertIn(value,source)

    def test_successor_quit_preserves_busy_backup_guard_and_updater_coordination(self):
        source=(MAC/'App/main.swift').read_text()
        body=source[source.index('func applicationShouldTerminate'):source.index('func applicationWillTerminate')]
        self.assertIn('backup?.isBusy == true && backup?.confirmQuitWhileBusy() != true',body)
        self.assertLess(body.index('if keepOpen { return .terminateCancel }'),body.index('return WizardUpdater.shared.shouldTerminate()'))

    def test_successor_keeps_backup_docs_tests_snapshot_and_factory_admission_fixture(self):
        for path in ('BACKUP.md','Package.swift','Shared/BackupContract.swift','App/WizardBackup.swift',
                     'Tests/Backup/BackupContractTests.swift','backup/qa/guest-snapshot.py',
                     'tools/check-factory-admission.py','Tests/test_factory_version_contract.py'):
            self.assertTrue((MAC/path).is_file(),path)

if __name__=='__main__':unittest.main(verbosity=2)
