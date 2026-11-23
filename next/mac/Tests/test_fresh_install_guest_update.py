#!/usr/bin/env python3
"""A fresh install gets this app's guest code before its first boot (try-wizard#137).

A new Mac downloads the published WizardOS disk (os/latest.json, still the 16 Oct 0.4.0 disk), while the app
bundle carries newer guest code (Contents/Resources/GuestUpdate, try-wizard#133). The bundled update used to run
only after an app update, so a fresh install booted the old setup page. Now the installer marks the new disk and the
first start applies the bundled update once, through the same stopped-disk snapshot and rollback as an app update.
"""
import sys
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def block(src, start, end):
    a = src.index(start)
    return src[a:src.index(end, a)]


class FreshInstallGuestUpdateTests(unittest.TestCase):
    def setUp(self):
        self.updater = (MAC / 'App/WizardUpdater.swift').read_text()
        self.main = (MAC / 'App/main.swift').read_text()
        self.fresh = block(self.updater, 'func admitFreshGuestUpdate() -> Bool', '    @objc func checkForUpdates')

    def test_installer_marks_the_new_disk_and_applies_before_first_start(self):
        done = block(self.main, 'installer.onDone = {', 'installer.install()')
        mark = done.index('WizardUpdater.markFreshInstall()')
        admit = done.index('if WizardUpdater.shared.admitFreshGuestUpdate() { return }')
        start = done.index('HostControl.send("start")')
        self.assertLess(mark, admit)
        self.assertLess(admit, start)

    def test_a_later_start_finishes_a_pending_fresh_update(self):
        begin = block(self.main, '    func begin() {', '    // MARK: Wizard UX')
        legacy = begin.index('admitLegacyBootstrap()')
        fresh = begin.index('guard !WizardUpdater.shared.admitFreshGuestUpdate() else { return }')
        self.assertLess(legacy, fresh)
        self.assertLess(fresh, begin.index('connectLocal()'))

    def test_marker_is_bound_to_the_installed_disk_and_used_once(self):
        mark = block(self.updater, 'static func markFreshInstall()', 'func admitFreshGuestUpdate')
        self.assertIn('WizardDiskIdentity.read(WizardShared.osDir.appendingPathComponent("disk.img"))', mark)
        self.assertIn('"state": "pending"', mark)
        self.assertIn('marker["diskIdentity"] as? String == WizardShared.diskIdentity', self.fresh)
        # Marked attempted before anything runs, so a failed try never loops.
        self.assertLess(self.fresh.index('marker["state"] = "attempted"'), self.fresh.index('WizardGuestActivation.shared.activate()'))

    def test_only_a_stopped_disk_and_a_build_that_carries_guest_code(self):
        self.assertLess(self.fresh.index('!HostControl.isRunning, !HostControl.hasForeignRunner'),
                        self.fresh.index('marker["state"] = "attempted"'))
        self.assertIn('release.guestPatch == "mac-stack-v1"', self.fresh)
        self.assertIn('Contents/Resources/GuestUpdate/runtime-bom.json', self.fresh)
        self.assertIn('try release.validate(Bundle.main.bundleURL)', self.fresh)

    def test_same_rollback_path_as_an_app_update(self):
        snap = self.fresh.index('try WizardGuestActivation.snapshotStoppedDisk()')
        journal = self.fresh.index('WizardUpdate.journal)')
        self.assertLess(snap, journal)
        self.assertIn('"applyGuest": true', self.fresh)
        self.assertIn('"phase": "installing"', self.fresh)
        # Never the legacy-cold path: that one is for 0.6.1-era disks and asks the owner first.
        self.assertNotIn('legacy-cold', self.fresh)
        self.assertNotIn('NSAlert', self.fresh)

    def test_failure_carries_on_with_the_downloaded_disk(self):
        done = block(self.fresh, 'WizardGuestActivation.shared.onDone', 'WizardGuestActivation.shared.activate()')
        self.assertIn('self.onGuestFinished()', done)
        self.assertNotIn('onActivationStatus(error', done)
        self.assertIn('removeItem(at: WizardGuestActivation.backup)', done)
        self.assertIn('WizardRollbackCleanup.start()', done)


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
