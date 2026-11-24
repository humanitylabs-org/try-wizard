#!/usr/bin/env python3
"""An app installed by hand from the DMG applies the guest update it carries, once (try-wizard#162).

Macs on 0.8.0-0.8.4 can't update themselves (#154), so they install 0.8.5+ from the DMG. Such an app has no Sparkle
journal and no fresh-install marker, so its bundled guest update (Contents/Resources/GuestUpdate) never ran. Now each
local start asks Shared/BundledGuestUpdate.swift whether this disk has this release's guest update, and applies it
through the same snapshot, journal and WizardGuestActivation path as an in-app update. The rule itself is tested by
Tests/BundledGuestUpdate (swift test); this checks the wiring.
"""
import re
import sys
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def block(src, start, end):
    a = src.index(start)
    return src[a:src.index(end, a)]


class HandInstallGuestUpdateTests(unittest.TestCase):
    def setUp(self):
        self.updater = (MAC / 'App/WizardUpdater.swift').read_text()
        self.main = (MAC / 'App/main.swift').read_text()
        self.activation = (MAC / 'App/WizardGuestActivation.swift').read_text()
        self.admit = block(self.updater, 'func admitBundledGuestUpdate() -> Bool', 'private func offerBundledGuest')
        self.finish = block(self.updater, 'func finishBundledGuestUpdate()', 'private func waitForBundledStop')
        self.apply = block(self.updater, 'private func applyBundledGuest(', '    // MARK: WizardOS updates')

    def test_every_local_start_asks_after_legacy_and_fresh_install(self):
        begin = block(self.main, '    func begin() {', '    // MARK: Wizard UX')
        fresh = begin.index('admitFreshGuestUpdate()')
        hand = begin.index('guard !WizardUpdater.shared.admitBundledGuestUpdate() else { return }')
        self.assertLess(begin.index('admitLegacyBootstrap()'), fresh)
        self.assertLess(fresh, hand)
        self.assertLess(hand, begin.index('connectLocal()'))

    def test_the_rule_is_built_into_the_app_and_tested(self):
        build = (MAC / 'build.sh').read_text()
        app_line = next(l for l in build.splitlines() if 'App/main.swift' in l and 'App/WizardUpdater.swift' in l)
        self.assertIn('Shared/BundledGuestUpdate.swift', app_line)
        package = (MAC / 'Package.swift').read_text()
        self.assertRegex(package, r'name: "WizardBundledGuestUpdate".*sources: \["BundledGuestUpdate.swift"\]')
        self.assertTrue((MAC / 'Tests/BundledGuestUpdate/BundledGuestUpdateTests.swift').exists())
        self.assertIn('WizardBundledGuestUpdate.decide(', self.updater)

    def test_receipt_names_its_release(self):
        success = block(self.activation, 'receipt["diskIdentity"] = identity', 'try WizardUpdate.write(receipt, receiptURL)')
        self.assertIn('receipt["releaseID"] = releaseID', success)
        self.assertIn('journal["releaseID"]', success)

    def test_applies_only_on_a_stopped_disk_with_nothing_recording(self):
        auto = self.admit.index('applyBundledGuest(release, automatic: true)')
        self.assertLess(self.admit.index('!HostControl.isRunning, !HostControl.hasForeignRunner, !isRecording(), !qaBusy'), auto)
        self.assertLess(self.admit.index('!handoverActive'), auto)   # an in-app update's own handover goes first
        self.assertIn('offerBundledGuest()', self.admit)
        self.assertIn('guard !HostControl.isRunning, !HostControl.hasForeignRunner, !isRecording(), !qaBusy', self.apply)

    def test_same_safe_path_as_an_in_app_update(self):
        marker = self.apply.index('Self.handInstallMarker)')
        snap = self.apply.index('try WizardGuestActivation.snapshotStoppedDisk()')
        journal = self.apply.index('WizardUpdate.journal)')
        activate = self.apply.index('WizardGuestActivation.shared.activate()')
        self.assertLess(marker, snap)       # recorded before anything runs: an automatic try happens once
        self.assertLess(snap, journal)
        self.assertLess(journal, activate)
        for key in ('"kind": "hand-install"', '"phase": "installing"', '"applyGuest": true', '"guestPatch": true',
                    '"releaseID": release.releaseID', 'try release.validate(Bundle.main.bundleURL)'):
            self.assertIn(key, self.apply)
        self.assertNotIn('legacy-cold', self.apply)
        self.assertNotIn('NSAlert', self.apply)
        # A failure says the old disk is back; it never deletes the owner's rollback copy.
        done = block(self.apply, 'WizardGuestActivation.shared.onDone', 'WizardGuestActivation.shared.activate()')
        self.assertIn('guest-rolled-back', done)
        self.assertIn('previous', done)
        self.assertNotIn('removeItem(at: WizardGuestActivation.backup)', done)
        self.assertIn('self.onGuestFinished()', done)

    def test_running_host_is_asked_with_finish_updating(self):
        self.assertIn('static let finishText = "Finish updating Wizard (about a minute)"', self.updater)
        self.assertIn('if phase == "guest-pending" && ready == nil { finishBundledGuestUpdate(); return }', self.updater)
        # Never during a recording or an unfinished chat, and the Host stops only when its guest is quiet.
        self.assertLess(self.finish.index('isRecording() || qaBusy'), self.finish.index('preparing = true'))
        self.assertIn('admitWebRestart', self.finish)
        self.assertIn('WizardUpdate.idle', self.finish)
        self.assertIn('HostControl.send("prepare-update")', self.finish)
        wait = block(self.updater, 'private func waitForBundledStop', 'private func bundledStopRefused')
        self.assertIn('state == "busy"', wait)
        self.assertLess(wait.index('state == "stopped", !HostControl.isRunning'), wait.index('applyBundledGuest(release, automatic: false)'))

    def test_bar_shows_a_named_button(self):
        show = block(self.updater, 'private func show(_ state: String', 'try? WizardUpdate.write(snapshot')
        self.assertIn('button: String? = nil', show)
        self.assertIn('action.title = button ??', show)
        self.assertTrue(re.search(r'action\.isHidden = !\(button != nil \|\|', show))


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
