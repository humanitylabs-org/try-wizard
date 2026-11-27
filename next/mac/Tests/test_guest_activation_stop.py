#!/usr/bin/env python3
"""try-wizard#191: the stop that ends a guest update's maintenance boot always settles the update.

On a fresh 0.8.18 Mac the guest applied its bundled update (receipt present), but the clean stop afterwards wasn't
confirmed, so the App left the journal at guest-activating: every later boot was a maintenance boot whose lease the
Host never gave back, and the guest refused all work ("update holds launch admission"). This runs the production
App/WizardGuestActivation.swift, unchanged, against a scripted Host (Tests/GuestActivationStop/main.swift) in five
modes and checks the end state (phase, the receipt's disk binding, the lease, the kind of boot), not only that a
receipt exists. It compiles with xcrun on macOS (CI). Elsewhere set WIZARD_SWIFT_DOCKER_IMAGE (e.g. swift:5.10-jammy)
to run it in a Linux Swift container; without either only the source checks run.

  python3 next/mac/Tests/test_guest_activation_stop.py [--source <checkout>]   # --source: A/B against another tree
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
MODES = ['ok', 'slow', 'busy', 'full-slow', 'failed-slow']


def build_and_run(source_mac: Path, out: Path) -> dict:
    """Compile the activation source of `source_mac` with this rig; return {mode: (exit code, output)}."""
    rig = MAC / 'Tests/GuestActivationStop/main.swift'
    files = [source_mac / 'Shared/DiskIdentity.swift', source_mac / 'App/WizardGuestActivation.swift', rig]
    results = {}
    if sys.platform == 'darwin':
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-module-cache-path', str(out / 'module-cache'),
                        *map(str, files), '-framework', 'AppKit', '-o', str(out / 'rig')], check=True)
        for mode in MODES:
            p = subprocess.run([str(out / 'rig'), str(out / ('home-' + mode)), mode], capture_output=True, text=True, timeout=600)
            results[mode] = (p.returncode, p.stdout + p.stderr)
        return results
    image = os.environ['WIZARD_SWIFT_DOCKER_IMAGE']
    for f in files:
        text = f.read_text().replace('import AppKit\n', 'import Foundation\n').replace('import Darwin\n', 'import Glibc\n')
        (out / f.name).write_text(text)
    run = ['docker', 'run', '--rm', '-v', f'{out}:/b', '-w', '/b', image]
    subprocess.run(run + ['swiftc', '-swift-version', '5', 'DiskIdentity.swift', 'WizardGuestActivation.swift', 'main.swift',
                          '-o', 'rig'], check=True, capture_output=True)
    for mode in MODES:
        p = subprocess.run(run + ['./rig', '/tmp/home', mode], capture_output=True, text=True, timeout=600)
        results[mode] = (p.returncode, p.stdout + p.stderr)
    return results


class GuestActivationStop(unittest.TestCase):
    def setUp(self):
        self.activation = (MAC / 'App/WizardGuestActivation.swift').read_text()
        self.host = (MAC / 'Host/main.swift').read_text()

    def test_busy_stop_is_asked_again_not_waited_out(self):
        wait = self.activation[self.activation.index('    private func waitStopped('):self.activation.index('    private func stopNotConfirmed(')]
        self.assertIn('"busy"', wait)
        self.assertIn('self.requestStop(migrationError, until: deadline)', wait)

    def test_only_a_code_only_apply_on_the_admitted_disk_is_activated_in_place(self):
        place = self.activation[self.activation.index('    private func activateInPlace('):self.activation.index('    private func completeStopped(')]
        self.assertIn('receipt["kind"] as? String == "code-only"', place)
        self.assertIn('journal["kind"] as? String != "legacy-cold"', place)
        self.assertIn('journal["diskIdentity"] as? String == identity', place)
        self.assertIn('if migrationError == nil, activateInPlace(text)', self.activation)

    def test_host_gives_the_maintenance_stop_a_longer_clean_budget(self):
        self.assertIn('static let maintenanceStopBudget: TimeInterval = 240', self.host)
        prepare = self.host[self.host.index('    private func prepareUpdate()'):self.host.index('    func refresh()')]
        self.assertIn('request["maintenance"] as? Bool == true ? VMController.maintenanceStopBudget : 90', prepare)
        self.assertIn('self.vm.stop(forceOnTimeout: false, budget: budget', prepare)
        # The App waits at least as long as the Host's lease ask (90 s) plus that budget.
        self.assertIn('static let stopWindow: TimeInterval = 360', self.activation)

    def test_production_activation_settles_every_stop_outcome(self):
        if sys.platform != 'darwin' and not (os.environ.get('WIZARD_SWIFT_DOCKER_IMAGE') and shutil.which('docker')):
            self.skipTest('needs macOS (xcrun) or WIZARD_SWIFT_DOCKER_IMAGE + docker')
        root = Path(os.environ.get('WIZARD_WORK_ROOT') or tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(prefix='guest-activation-stop-', dir=root) as out:
            results = build_and_run(MAC, Path(out))
        for mode, (code, output) in results.items():
            with self.subTest(mode=mode):
                self.assertEqual(code, 0, output)
                self.assertIn(f'GUEST_ACTIVATION_STOP_{mode.upper()}_PASS', output)


def ab(source: Path):
    """Print each mode's verdict for another checkout (e.g. origin/main), for before/after evidence."""
    root = Path(os.environ.get('WIZARD_WORK_ROOT') or tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix='guest-activation-stop-', dir=root) as out:
        for mode, (code, output) in build_and_run(source / 'next/mac', Path(out)).items():
            print(f'== {mode}: exit {code}')
            print('\n'.join(line for line in output.splitlines() if line.startswith(('RESULT', 'GUEST_ACTIVATION'))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--source', type=Path)
    known, rest = parser.parse_known_args()
    if known.source:
        ab(known.source.resolve())
    else:
        unittest.main(argv=[sys.argv[0], *rest])
