#!/usr/bin/env python3
"""Light source contracts; the companion manifest test executes actual Swift on Mac."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class FactoryVersionContract(unittest.TestCase):
    def test_installer_abi_admission(self):
        source = (ROOT / 'App/main.swift').read_text()
        check = source[source.index('static func verifyManifest(in'):source.index('static func freshStaging()')]
        self.assertIn('try WizardGuestABI.image(m)', check)
        self.assertNotIn('.contains(imageVersion)', check)
        self.assertIn('!files.isEmpty else { throw bad }', check)
        self.assertIn('guard got == want.lowercased() else { throw bad }', check)

    def test_precomposed_abi_admission(self):
        source = (ROOT / 'Shared/Shared.swift').read_text()
        check = source[source.index('static var legacyBootstrapNeeded'):source.index('static var diskIdentity')]
        self.assertIn('WizardGuestABI.image(manifest), abi >= 1', check)
        self.assertIn('WizardDiskIdentity.completed(receipt, modern: modern', check)

    def test_current_release_contract(self):
        release = json.loads((ROOT / 'release-0.7.1.json').read_text())
        self.assertEqual((release['nativeVersion'], release['nativeBuild'], release['guestVersion']), ('0.7.1', '308', '0.4.1'))

if __name__ == '__main__':
    unittest.main()
