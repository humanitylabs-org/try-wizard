#!/usr/bin/env python3
"""Brand ownership/provenance and exact ICNS representation regression."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MAC = ROOT / 'next/mac'
ASSETS = MAC / 'assets/brand'
spec = importlib.util.spec_from_file_location('brand_icon', MAC / 'assets/build-icon.py')
assert spec is not None and spec.loader is not None
icon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icon)

class BrandTests(unittest.TestCase):
    def test_provenance_bytes(self):
        manifest = json.loads((ASSETS/'provenance.json').read_text())
        for name, expected in manifest['generated_sha256'].items():
            if (ASSETS/name).exists():
                self.assertEqual(hashlib.sha256((ASSETS/name).read_bytes()).hexdigest(), expected)
        for name, expected in manifest['source_sha256'].items():
            self.assertEqual(hashlib.sha256((ASSETS/'originals'/name).read_bytes()).hexdigest(), expected)

    def test_lossless_icns(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/'Wizard.icns'
            icon.pack(ASSETS, output)
            data = output.read_bytes()
            self.assertEqual(data[:4], b'icns')
            self.assertEqual(struct.unpack('>I',data[4:8])[0], len(data))
            pos = 8
            for kind, size in icon.REPRESENTATIONS:
                self.assertEqual(data[pos:pos+4], kind)
                n = struct.unpack('>I',data[pos+4:pos+8])[0]
                self.assertEqual(data[pos+8:pos+n], (ASSETS/('wizard-icon-%s.png'%size)).read_bytes())
                pos += n
            self.assertEqual(pos,len(data))

    def test_native_consumers(self):
        for name in ('App/main.swift','App/WizardKeys.swift','Host/main.swift'):
            source = (MAC/name).read_text()
            self.assertNotIn('wand.and.stars',source)
            self.assertNotIn('labelWithString: "✦"',source)
            self.assertIn('WizardBrand.',source)
        build = (MAC/'build.sh').read_text()
        self.assertIn('assets/build-icon.py',build)
        self.assertNotIn('if [[ -f assets/Wizard.icns',build)
        self.assertIn('Shared/Brand.swift',build)
        self.assertIn('min(18, 18 * ratio)',(MAC/'Shared/Brand.swift').read_text())
        self.assertIn('next/mac/assets/brand/wizard-icon-1024.png',(ROOT/'macos/build-app.sh').read_text())

    def test_bundle_name_is_wizardos(self):
        # try-wizard#100: Dock, Finder, Cmd-Tab and Privacy & Security show WizardOS. The bundle id, the
        # Application Support data folder, the Host bundle and the update feed URL keep their names so
        # existing installs update in place.
        import plistlib, re
        build = (MAC/'build.sh').read_text()
        body = build[build.index('plist() {'):build.index('\nEOF\n}')]
        body = body[body.index('<?xml'):]
        xml = body.replace('$VER', '1').replace('$BUILD', '1').replace('$5', '').replace('$3', 'org.humanitylabs.wizard.mvp').replace('$4', 'Wizard')
        call = re.search(r'plist "\$APP/Contents/Info.plist" "([^"]+)" (\S+) (\S+)', build)
        self.assertIsNotNone(call)
        info = plistlib.loads(xml.replace('$2', call.group(1)).encode())
        self.assertEqual(info['CFBundleDisplayName'], 'WizardOS')
        self.assertEqual(info['CFBundleName'], 'WizardOS')
        self.assertEqual(call.group(2), 'org.humanitylabs.wizard.mvp')
        self.assertIn('plist "$HOST/Contents/Info.plist" "Wizard Host" org.humanitylabs.wizard.mvp.host', build)
        self.assertIn('"$STAGE/WizardOS.app"', build)
        self.assertNotIn('"Wizard MVP"', build)
        self.assertIn("SPARKLE_FEED=${SPARKLE_FEED:-https://downloads.aiwizards.com/mac/appcast.xml}", build)
        self.assertIn('return base.appendingPathComponent("Wizard MVP", isDirectory: true)', (MAC/'Shared/Shared.swift').read_text())
        self.assertNotIn('under Wizard MVP', (MAC/'App/main.swift').read_text())
        self.assertNotIn('Wizard MVP', (MAC/'tools/make-update-feed.py').read_text())

    def test_guest_onboarding_and_semantic_icon(self):
        static = ROOT/'next/guest/overlay/opt/wizard/setup/static'
        html = (static/'index.html').read_text()
        for name in ('wizard-mark-white.png','wizard-icon-32.png'):
            self.assertIn('/static/'+name,html)
            self.assertEqual((static/name).read_bytes(),(ASSETS/name).read_bytes())
        self.assertIn('data-kind="chatgpt"><span class="ico">✦</span>',html)

if __name__ == '__main__':
    unittest.main()
