#!/usr/bin/env python3
"""A guest update asks the maintenance lease again while the guest is still settling (try-wizard#191).

On a fresh Mac the bundled guest update asked for the lease seconds after the 0.4.0 guest booted. The guest's lease
helper couldn't read its runtime containers yet (docker ps/inspect/exec failed: runtime_control_failed), the Host
wrote that refusal as the guest update's answer, and the app rolled the update back for good, although the same lease
was granted a second later (the rollback's own stop got it). The Host now runs the lease through WizardLeaseRetry
(Shared/LeaseRetry.swift, XCTest Tests/LeaseRetry): "not ready yet" refusals are asked again every 5 s for up to
4 minutes; work that is running, and any answer that isn't the Mac-line lease, still go back at once.
"""
import re
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def block(src, start, end):
    a = src.index(start)
    return src[a:src.index(end, a)]


class LeaseRetryWiringTests(unittest.TestCase):
    def setUp(self):
        self.host = (MAC / 'Host/main.swift').read_text()
        self.rule = (MAC / 'Shared/LeaseRetry.swift').read_text()

    def test_guest_update_lease_goes_through_the_retry(self):
        guest = block(self.host, '    private func applyGuestUpdate()', '    private func admitStandardGuest(')
        call = guest[guest.index('WizardLeaseRetry.acquire('):]
        # The one lease ask is the same as before (standard guests still take the onMissing path)...
        self.assertIn('WizardUpdate.maintenance(nonce, onMissing: { [weak self] in self?.admitStandardGuest(answer) }, answer)', call)
        # ...a half-taken lease is released with the same token, retries run on the main queue, and the final
        # answer goes to the same apply step (which writes guest-response.json).
        self.assertIn('WizardUpdate.maintenance(nonce, release: true)', call)
        self.assertIn('DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: next)', call)
        self.assertIn('done: apply)', call)
        # Cold bootstrap still has no lease to ask for.
        self.assertLess(guest.index('if WizardShared.coldBootstrapToken != nil { apply(nil) }'), guest.index('WizardLeaseRetry.acquire('))

    def test_retry_is_bounded_and_only_for_lease_refusals(self):
        interval = float(re.search(r'static let interval: TimeInterval = (\d+)', self.rule).group(1))
        window = float(re.search(r'static let window: TimeInterval = (\d+)', self.rule).group(1))
        self.assertGreaterEqual(interval, 1)
        # Well inside the window's own deadline for the guest update (WizardGuestActivation waitApplied: 950 s).
        self.assertLessEqual(window, 300)
        self.assertIn('static let leasePrefix = "Local maintenance deferred:"', self.rule)
        update = (MAC / 'Shared/UpdateContract.swift').read_text()
        self.assertIn('done(ok ? nil : "Local maintenance deferred:', update)
        self.assertIn('guard let reason, reason.hasPrefix(leasePrefix), elapsed < window else { return .done }', self.rule)
        activation = (MAC / 'App/WizardGuestActivation.swift').read_text()
        self.assertIn('waitApplied(nonce, Date().addingTimeInterval(950))', activation)

    def test_work_refusals_stay_final(self):
        # The guest's busy texts (wizard-agent-service server/maintenance.mjs maintenanceReason).
        for needle in ('"is still working"', '"Hermes session was started outside"', '"command-line or terminal session"',
                       '"runtime_operation_in_flight"', '"maintenance_token_mismatch"'):
            self.assertIn(needle, self.rule)

    def test_host_build_and_package_compile_the_rule(self):
        line = next(l for l in (MAC / 'build.sh').read_text().splitlines() if 'Host/main.swift' in l and 'SWIFTC' in l)
        self.assertIn('Shared/LeaseRetry.swift', line)
        pkg = (MAC / 'Package.swift').read_text()
        self.assertIn('sources: ["LeaseRetry.swift"]', pkg)
        tests = (MAC / 'Tests/LeaseRetry/LeaseRetryTests.swift').read_text()
        self.assertIn('func testLeaseThatFailsOnceThenSucceedsIsGranted()', tests)


if __name__ == '__main__':
    unittest.main()
