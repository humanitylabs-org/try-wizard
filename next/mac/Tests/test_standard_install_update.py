#!/usr/bin/env python3
"""try-wizard#154: a Wizard.app update on a standard-install VM (no Mac-line /wizard/v1/maintenance route).

The Swift is compiled and its decision unit-tested by CI (`swift test`, Tests/StandardAdmission); these checks pin the
wiring that only a Mac would otherwise show, and run the guest's wizard-ctl `work` command for real.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
ROOT = MAC.parents[1]
CTL = ROOT / 'next/guest/overlay/opt/wizard/bin/wizard-ctl'


def block(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i + len(start))]


class StandardInstallAdmission(unittest.TestCase):
    def test_lease_404_hands_over_only_when_asked(self):
        src = (MAC / 'Shared/UpdateContract.swift').read_text()
        m = block(src, 'static func maintenance(', 'static func releaseMaintenance(')
        self.assertIn('onMissing: (() -> Void)? = nil', m)
        # Only a 404 on the lease request (never on release) and only for a caller that passes onMissing.
        self.assertIn('let noLeaseRoute = code == 404 || (code == 401 && body?["error"] as? String == "shell_token_required")', m)
        self.assertIn('if !release, noLeaseRoute, let onMissing {', m)
        self.assertIn('removeItem(at: maintenanceJournal)', m.split('if !release, noLeaseRoute')[1].split('onMissing(); return')[0])
        # Everything else still refuses as before (Tests/LegacyAdmission: 404 without onMissing is refused).
        self.assertIn('done(ok ? nil : "Local maintenance deferred:', m)

    def test_host_uses_standard_check_for_app_update_and_guest_patch(self):
        host = (MAC / 'Host/main.swift').read_text()
        prepare = block(host, '    private func prepareUpdate()', '    func refresh()')
        self.assertIn('WizardUpdate.maintenance(nonce, onMissing: { [weak self] in self?.admitStandardGuest(stopWhenIdle) }, stopWhenIdle)', prepare)
        self.assertIn('self.vm.stop(forceOnTimeout: false', prepare)
        guest = block(host, '    private func applyGuestUpdate()', '    private func admitStandardGuest(')
        self.assertIn('WizardUpdate.maintenance(nonce, onMissing: { [weak self] in self?.admitStandardGuest(apply) }, apply)', guest)
        admit = block(host, '    private func admitStandardGuest(', '    private func prepareUpdate()')
        for needle in ('vm.control("work"', 'vm.control("update-status"', 'WizardShared.localUXHealthURL',
                       'WizardStandardAdmission.reason(work: work, status: status, health: health)'):
            self.assertIn(needle, admit)

    def test_host_build_compiles_the_decision(self):
        line = next(l for l in (MAC / 'build.sh').read_text().splitlines() if 'Host/main.swift' in l and 'SWIFTC' in l)
        self.assertIn('Shared/StandardAdmission.swift', line)
        pkg = (MAC / 'Package.swift').read_text()
        self.assertIn('sources: ["StandardAdmission.swift"]', pkg)
        self.assertTrue((MAC / 'Tests/StandardAdmission/StandardAdmissionTests.swift').exists())

    def test_window_says_it_waits_and_retries(self):
        up = (MAC / 'App/WizardUpdater.swift').read_text()
        wait = block(up, '    private func waitForHost(', '    private func install()')
        self.assertIn('if state == "busy" { deferBusy(', wait)
        self.assertNotIn('state == "failed" || state == "busy"', wait)
        defer = block(up, '    private func deferBusy(', '    private func fail(')
        self.assertNotIn('Update failed', defer)
        self.assertIn('self.updateAndRestart()', defer)
        self.assertIn('self.ready != nil, !self.preparing', defer)
        self.assertIn('static let busyRetryFor: TimeInterval = 6 * 3600', defer)
        # Later stops the asking again.
        self.assertIn('waitToken = UUID(); waitingSince = nil }', up)


class WizardCtlWork(unittest.TestCase):
    """Runs the real wizard-ctl with a fake sudo/wam on PATH."""

    def run_ctl(self, wam_out):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d)
            (b / 'sudo').write_text('#!/bin/bash\n# sudo -iu wizard [env K=V ...] wam ...\nshift 2\n'
                                    '[ "$1" = env ] && { shift; while [[ "$1" == *=* ]]; do shift; done; }\nexec "$@"\n')
            (b / 'wam').write_text('#!/bin/bash\n[ "$1" = work ] && printf %s "$WAM_OUT"\nexit 0\n')
            for f in ('sudo', 'wam'):
                (b / f).chmod(0o755)
            env = {**os.environ, 'PATH': f'{b}:{os.environ["PATH"]}', 'WAM_OUT': wam_out}
            return subprocess.run(['bash', str(CTL)], input='work\n', capture_output=True, text=True, env=env, timeout=20).stdout

    def test_work_prints_wam_work(self):
        self.assertEqual(self.run_ctl('[{"kind": "agent", "name": "A chat reply"}]').strip(),
                         '[{"kind": "agent", "name": "A chat reply"}]')

    def test_older_app_manager_reads_as_unknown_command(self):
        self.assertEqual(self.run_ctl('').strip(), 'unknown')


if __name__ == '__main__':
    unittest.main(verbosity=2)
