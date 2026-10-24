#!/usr/bin/env python3
"""The factory and runtime must fail closed before executing unpinned input."""
import copy
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_pins', ROOT / 'release-pins.py')
assert spec and spec.loader
pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pins)


class ReleasePins(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'releases/mac-launch-20261027/pins.json').read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'pins.json'

    def load(self):
        self.path.write_text(json.dumps(self.manifest))
        return pins.load(self.path)

    def test_exact_selected_commits(self):
        _, s = self.load()
        for name in ('ux', 'service', 'wam'):
            self.assertEqual(s[name], self.manifest['finalPins'][name])

    def test_no_mutable_source(self):
        self.manifest['sourceInputs'][self.manifest['runtimeSelected']['service']]['commit'] = 'main'
        with self.assertRaises(ValueError):
            self.load()

    def test_no_mutable_installer(self):
        self.manifest['osInstaller']['url'] = 'https://aiwizards.com/os.sh'
        with self.assertRaises(ValueError):
            self.load()

    def test_installer_must_belong_to_selected_wam(self):
        self.manifest['runtimeSelected']['wam'] = 'wam-main'
        with self.assertRaises(ValueError):
            self.load()

    def test_installer_requires_sha256(self):
        self.manifest['osInstaller']['sha256'] = '1234'
        with self.assertRaises(ValueError):
            self.load()

    def test_image_tags_are_not_pins(self):
        self.manifest['runtimeBuild']['wamImage'] = 'ghcr.io/humanitylabs-org/wizard-app-manager:latest'
        with self.assertRaises(ValueError):
            self.load()

    def test_unknown_factory_rejected(self):
        self.manifest['factory']['version'] = '0.6.0'
        with self.assertRaises(ValueError):
            self.load()

    def test_no_relabelling_retained_factory(self):
        self.manifest['factory']['version'] = '0.4.0'
        with self.assertRaises(ValueError):
            self.load()

    def test_factory_reads_manifest_before_work(self):
        source = (ROOT / 'build-image.sh').read_text()
        self.assertIn('WIZARD_PINS', source)
        self.assertLess(source.index('release-pins.py'), source.index('docker build'))
        self.assertNotIn('1eab0eb991e4031f3fd992c9745f0f9d9f4bfd7a', source)

    def test_download_verified_before_initial_execution(self):
        s = (ROOT / 'overlay/opt/wizard/bin/wizard-provision').read_text()
        self.assertLess(s.index('sha256sum -c -'), s.index('bash /tmp/os.sh'))
        self.assertIn('WAM_REF="$WAM_COMMIT"', s)
        self.assertNotIn('https://aiwizards.com/os.sh', s)
        self.assertNotIn('checkout -q', s)

    def test_runtime_has_no_hardcoded_source_defaults(self):
        s = (ROOT / 'build-runtime-payload.py').read_text()
        self.assertIn("p.add_argument('--pins',type=Path,required=True)", s)
        self.assertIn("assert pins==expected", s)
        self.assertNotIn('31bdc3ecb0586f61323b72227ab70506d2627e5d', s)

    def test_managed_runtime_has_no_mutable_base(self):
        source = (ROOT / 'managed-launch/Dockerfile').read_text()
        self.assertIn('ARG HERMES_IMAGE', source)
        self.assertEqual(source.count('FROM ${HERMES_IMAGE}'), 2)
        self.assertNotIn('v2026.9.24-wizard-slim1', source)
        runtime = (ROOT / 'build-runtime-payload.py').read_text()
        self.assertIn("'HERMES_IMAGE='+hermes_ref", runtime)
        self.assertIn("'image_id':stock['Id']", runtime)


if __name__ == '__main__':
    unittest.main()
