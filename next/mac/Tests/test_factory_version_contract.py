#!/usr/bin/env python3
"""Light source contracts; the companion manifest test executes actual Swift on Mac."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class FactoryVersionContract(unittest.TestCase):
    def test_installer_exact_version_allowlist(self):
        source = (ROOT / 'App/main.swift').read_text()
        check = source[source.index('static func verifyManifest(in'):source.index('static func freshStaging()')]
        match = re.search(r'(\[[^\n]+\])\.contains\(imageVersion\)', check)
        self.assertIsNotNone(match)
        versions = set(json.loads(match[1]))
        self.assertEqual(versions, {'0.3.0', '0.4.0', '0.4.1', '0.5.0'})
        self.assertNotIn('0.4.9', versions)
        self.assertIn('!files.isEmpty else { throw bad }', check)
        self.assertIn('guard got == want.lowercased() else { throw bad }', check)

    def test_precomposed_exact_version_allowlist(self):
        source = (ROOT / 'Shared/Shared.swift').read_text()
        check = source[source.index('static var legacyBootstrapNeeded'):source.index('static var diskIdentity')]
        match = re.search(r'Set\((\[[^\n]+\])\)\.contains\(version\) \{ return false \}', check)
        self.assertIsNotNone(match)
        self.assertEqual(set(json.loads(match[1])), {'0.4.0', '0.4.1', '0.5.0'})
        self.assertNotIn('0.4.9', json.loads(match[1]))
        self.assertIn('WizardDiskIdentity.completed(receipt, modern: modern', check)

    def test_current_release_contract(self):
        release = json.loads((ROOT / 'release-0.7.2.json').read_text())
        self.assertEqual((release['nativeVersion'], release['nativeBuild'], release['factoryVersion']), ('0.7.2', '309', '0.5.0'))

if __name__ == '__main__':
    unittest.main()
