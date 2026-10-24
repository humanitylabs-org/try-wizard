import importlib.util
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAC = ROOT / 'mac'
spec = importlib.util.spec_from_file_location('guest_contract', ROOT / 'guest/update-contract.py')
assert spec and spec.loader
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class GuestABIContract(unittest.TestCase):
    def test_legacy_inference(self):
        for version, abi in {'0.3.0': 0, '0.4.0': 1, '0.4.1': 1}.items():
            self.assertEqual(policy.image_abi({'version': version}), abi)
        source = (MAC / 'Shared/UpdateContract.swift').read_text()
        table = re.search(r'static let legacy = (\[[^\n]+\])', source)[1]
        self.assertEqual(json.loads('{' + table[1:-1] + '}'), policy.LEGACY_ABI)

    def test_explicit_abi_makes_version_display_only(self):
        for abi in (0, 1):
            self.assertEqual(policy.image_abi({'version': 'future-display-name', 'guestABI': abi}), abi)

    def test_unknown_abi_never_falls_back(self):
        for raw in (None, True, False, '1', 1.0, -1, 2, 999):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                policy.image_abi({'version': '0.4.1', 'guestABI': raw})
        with self.assertRaises(ValueError):
            policy.image_abi({'version': '0.4.9'})

    def test_payload_range(self):
        for abi in (0, 1):
            policy.admit_payload({'guestABI': {'min': 0, 'max': 1}}, abi)
        for bounds in ({}, {'min': 1, 'max': 0}, {'min': 0, 'max': 2}, {'min': False, 'max': 1}):
            with self.assertRaises(ValueError):
                policy.admit_payload({'guestABI': bounds}, 1)
        with self.assertRaises(ValueError):
            policy.admit_payload({'guestABI': {'min': 1, 'max': 1}}, 0)

    def test_installer_preserves_integrity_loop_byte_for_byte(self):
        path = 'next/mac/App/main.swift'
        repo = ROOT.parent
        old = subprocess.check_output(['git', 'show', '84720ac:' + path], cwd=repo, text=True)
        new = (repo / path).read_text()
        def loop(s):
            s = s[s.index('static func verifyManifest'):s.index('static func freshStaging')]
            return s[s.index('        for (rel, want) in files {'):]
        self.assertEqual(loop(old), loop(new))
        self.assertIn('try WizardGuestABI.image(m)', new)
        host = (MAC / 'Host/main.swift').read_text()
        self.assertIn('try WizardGuestABI.image(', host[host.index('    func start() {', host.index('class')):])


if __name__ == '__main__':
    unittest.main()
