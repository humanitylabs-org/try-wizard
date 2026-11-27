#!/usr/bin/env python3
"""Mac app updates can't wait forever (try-wizard#128, on for every Mac).

The rules (Later until tomorrow, 3 days then offer on quit, critical has no Later, ready since kept per build) are in
Shared/ReadyUpdate.swift and tested by Tests/ReadyUpdate (swift test). This checks the wiring in the app: everything
new runs on every Mac (the old switch is gone), the quit sheet goes through Update and restart's guards, and Install and quit lets Sparkle
install on termination instead of relaunching.
"""
import re
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def block(src, start, end):
    a = src.index(start)
    return src[a:src.index(end, a + len(start))]


class UpdateDeadlinesWiring(unittest.TestCase):
    def setUp(self):
        self.up = (MAC / 'App/WizardUpdater.swift').read_text()
        self.main = (MAC / 'App/main.swift').read_text()

    def test_switch_is_gone_and_its_value_cleared(self):
        clock = block(self.main, 'enum WizardUpdateDeadlines {', '\n}\n')
        self.assertNotIn('isOn', clock)
        self.assertNotIn('static let key', clock)
        self.assertNotIn('WizardUpdateDeadlines.isOn', self.up + self.main)
        self.assertNotIn('UpdateDeadlines -bool YES', self.main + (MAC / 'UPDATER.md').read_text())
        launch = block(self.main, 'func applicationDidFinishLaunching', 'buildMenus()')
        self.assertIn('UserDefaults.standard.removeObject(forKey: "UpdateDeadlines")', launch)
        # The QA clock (Done when 1: "with the clock moved forward a day").
        self.assertIn('UpdateDeadlinesClockOffset', clock)

    def test_rules_are_built_in_and_tested(self):
        build = (MAC / 'build.sh').read_text()
        app_line = next(l for l in build.splitlines() if 'App/main.swift' in l and 'App/WizardUpdater.swift' in l)
        self.assertIn('Shared/ReadyUpdate.swift', app_line)
        self.assertRegex((MAC / 'Package.swift').read_text(), r'name: "WizardReadyUpdate".*sources: \["ReadyUpdate.swift"\]')
        self.assertTrue((MAC / 'Tests/ReadyUpdate/ReadyUpdateTests.swift').exists())
        rules = (MAC / 'Shared/ReadyUpdate.swift').read_text()
        self.assertEqual(len(re.findall(r'3 \* 24 \* 3600', rules)), 1)   # the 3 days, in one constant
        self.assertNotRegex(self.up, r'3 \* 24 \* 3600|259200')

    def test_every_path_runs_on_every_mac(self):
        later = block(self.up, '@objc private func laterPressed()', '\n    }\n')
        self.assertIn('hideNotice()', later.split('guard')[0])          # Later still hides the bar first
        self.assertIn('guard ready != nil, let record = readyRecord', later)
        self.assertIn('later.action = #selector(laterPressed)', self.up)
        start = block(self.up, 'func start() {', '\n    }\n')
        self.assertIn('            watchLater()   // try-wizard#128', start)
        offer = block(self.up, 'private func offerOnQuit() -> Bool', '\n    }\n')
        self.assertIn('guard !quitAsked, ready != nil,', offer)
        ready = block(self.up, 'func showReady(toInstallAndRelaunch', '\n    }\n')
        self.assertIn('let hidden = noteReady()', ready)
        self.assertIn('incomingCritical = item.isCriticalUpdate', self.up)
        show = block(self.up, 'private func show(_ state: String', '\n    }\n')
        self.assertIn('later.isHidden = !WizardReadyUpdate.showsLater(critical: incomingCritical, phase: state)', show)
        # installingOnQuit is only ever set from the sheet's Install and quit.
        sets = re.findall(r'installingOnQuit = true', self.up)
        self.assertEqual(len(sets), 1)
        self.assertIn('self.installingOnQuit = true\n            self.updateAndRestart()', self.up)

    def test_quit_asks_before_the_old_skip(self):
        term = block(self.up, 'func shouldTerminate() -> NSApplication.TerminateReply {', '\n    }\n')
        self.assertLess(term.index('if restartAuthorized { return .terminateNow }'), term.index('offerOnQuit()'))
        self.assertLess(term.index('if preparing { return .terminateCancel }'), term.index('offerOnQuit()'))
        self.assertLess(term.index('offerOnQuit()'), term.index('reply(.skip)'))

    def test_sheet_offers_install_first_and_never_installs_silently(self):
        ask = block(self.up, 'private func askInstallOnQuit()', 'private func cannotUpdateOnQuit(')
        self.assertLess(ask.index('WizardReadyUpdate.installAndQuit'), ask.index('WizardReadyUpdate.quitWithoutUpdating'))
        self.assertIn('answer == .alertFirstButtonReturn', ask)
        # A recording or agent work: say it can't update now, then quit without updating.
        self.assertLess(ask.index('isRecording() || qaBusy'), ask.index('let alert = NSAlert()'))
        self.assertIn('cannotUpdateOnQuit(', ask)

    def test_guards_that_say_no_quit_without_updating(self):
        wait = block(self.up, 'private func waitThenRetry(_ text: String) {', '\n    }\n')
        self.assertIn('if installingOnQuit { cannotUpdateOnQuit(text); return }', wait.split('show("busy"')[0])
        fail = block(self.up, 'private func fail(_ text: String) {', '\n    }\n')
        self.assertLess(fail.index('releaseLease()'), fail.index('if installingOnQuit { cannotUpdateOnQuit(text); return }'))
        self.assertLess(fail.index('HostControl.ensureRunning()'), fail.index('if installingOnQuit'))
        restart = block(self.up, '@objc func updateAndRestart() {', 'private func prepareIdleHost()')
        self.assertIn('if installingOnQuit { cannotUpdateOnQuit("Another candidate', restart)
        # Update and restart's own guards stay in front: admitWebRestart, the Host stop, the lease.
        self.assertIn('admitWebRestart', restart)
        self.assertIn('self.prepareIdleHost()', restart)

    def test_install_and_quit_installs_on_termination_without_relaunch(self):
        approved = block(self.up, 'private func installApproved() {', 'private func releaseLease()')
        quit = approved.index('if installingOnQuit {')
        self.assertLess(approved.index('restartAuthorized = true'), quit)
        self.assertLess(approved.index('journal["phase"] = "installing"'), quit)
        branch = approved[quit:approved.index('reply(.install)')]
        self.assertIn('NSApp.terminate(nil)', branch)
        self.assertNotIn('reply(', branch)   # no .install reply: that would relaunch

    def test_ready_record_is_kept_with_the_update_state(self):
        self.assertIn('WizardUpdate.dir.appendingPathComponent("ready.json")', self.up)
        self.assertIn('WizardReadyUpdate.ready(readyRecord, build: version, critical: incomingCritical', self.up)

    def test_settings_hears_a_critical_release_as_urgent(self):
        # Ask 3: the page's update status (try-wizard#126) carries urgent for a critical release.
        self.assertIn('urgent: incomingCritical)', self.up)
        status = (MAC / 'Shared/AppUpdateStatus.swift').read_text()
        self.assertIn('if urgent && showsLatest && phase != "manual" { object["urgent"] = true }', status)


if __name__ == '__main__':
    unittest.main()
