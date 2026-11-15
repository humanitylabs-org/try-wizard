#!/usr/bin/env python3
"""The Mac app can show the PWA/phone app icon instead of the flat purple square (try-wizard#86).

It ships off by default behind the `PWAIcon` user default. With the switch on, the running app's Dock icon is the
same dark Void tile as the PWA; the bundle icon, name, bundle id and the `Wizard MVP` data folder stay unchanged.
"""
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
BRAND = MAC / 'assets/brand'
PWA = BRAND / 'pwa'
spec = importlib.util.spec_from_file_location('brand_icon', MAC / 'assets/build-icon.py')
assert spec is not None and spec.loader is not None
icon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icon)


def block(source: str, start: str, end: str) -> str:
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError('%r not found' % start)
    return source[i:j]


class PWAIconTests(unittest.TestCase):
    def setUp(self):
        self.main = (MAC / 'App/main.swift').read_text()
        self.build = (MAC / 'build.sh').read_text()

    def test_pwa_icon_set_is_complete_and_hashed(self):
        manifest = json.loads((PWA / 'provenance.json').read_text())['generated_sha256']
        for _, size in icon.REPRESENTATIONS:
            name = 'wizard-icon-%d.png' % size
            data = (PWA / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest[name], name)

    def test_pwa_icon_differs_from_default_icon(self):
        # The default (switch off) icon is untouched; the PWA set is a different picture.
        self.assertNotEqual((PWA / 'wizard-icon-1024.png').read_bytes(), (BRAND / 'wizard-icon-1024.png').read_bytes())

    def test_pwa_icns_packs_losslessly(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'WizardPWA.icns'
            icon.pack(PWA, out, marks=False)
            data = out.read_bytes()
            self.assertEqual(data[:4], b'icns')
            self.assertEqual(struct.unpack('>I', data[4:8])[0], len(data))
            pos = 8
            for kind, size in icon.REPRESENTATIONS:
                self.assertEqual(data[pos:pos + 4], kind)
                n = struct.unpack('>I', data[pos + 4:pos + 8])[0]
                self.assertEqual(data[pos + 8:pos + n], (PWA / ('wizard-icon-%d.png' % size)).read_bytes())
                pos += n
            self.assertEqual(pos, len(data))

    def test_build_ships_pwa_icns_beside_default_icon(self):
        self.assertIn('assets/build-icon.py assets/brand/pwa "$OUT/obj/WizardPWA.icns" --no-marks', self.build)
        self.assertIn('cp "$OUT/obj/WizardPWA.icns" "$APP/Contents/Resources/WizardPWA.icns"', self.build)
        # The bundle icon stays the default one, so Finder and existing installs see no change while the switch is off.
        self.assertIn('<key>CFBundleIconFile</key><string>Wizard</string>', self.build)
        self.assertIn('org.humanitylabs.wizard.mvp', self.build)

    def test_switch_is_off_by_default_and_only_sets_the_dock_icon(self):
        body = block(self.main, 'enum WizardPWAIcon', '\n}\n')
        self.assertIn('static let key = "PWAIcon"', body)
        self.assertRegex(body, r'static var isOn: Bool \{ UserDefaults\.standard\.bool\(forKey: key\) \}')
        self.assertIn('guard isOn', body)
        self.assertIn('forResource: resource, ofType: "icns"', body)
        self.assertIn('static let resource = "WizardPWA"', body)
        self.assertIn('NSApp.applicationIconImage = image', body)
        self.assertNotIn('setIcon(', body, 'never write a custom icon into the signed bundle')

    def test_applied_at_launch(self):
        launch = block(self.main, 'func applicationDidFinishLaunching', 'controller.showWindow(nil)')
        self.assertIn('WizardPWAIcon.apply()', launch)


if __name__ == '__main__':
    unittest.main()
