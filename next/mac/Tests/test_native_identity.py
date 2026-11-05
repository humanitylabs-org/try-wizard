#!/usr/bin/env python3
"""Targeted source/fixture regressions; real-bundle verifier runs separately on Thales."""
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile
import unittest

MAC=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('identity',MAC/'tools/verify-native-identity.py')
assert spec and spec.loader
identity=importlib.util.module_from_spec(spec); spec.loader.exec_module(identity)


class NativeIdentityTests(unittest.TestCase):
    def test_maintenance_regeneration_preserves_committed_bytes(self):
        try: import PIL
        except ImportError: self.skipTest('Pillow maintenance-only dependency absent; native pack/pixel tests still run')
        if PIL.__version__ != '12.3.0':
            self.skipTest('Pillow 12.3.0 maintenance check requires its pinned environment; native builds use stdlib only')
        with tempfile.TemporaryDirectory() as tmp:
            assets=Path(tmp)/'brand'
            shutil.copytree(identity.DARK,assets/'dark')
            identity.icon.prepare_dark(assets)

    def test_native_contract_hashes_text_not_code_signature(self):
        # Explicit Mach-O-shaped fixture, not a compiled program or native proof.
        fixture=bytearray(256); struct.pack_into('<I',fixture,0,0xfeedfacf)
        struct.pack_into('<I',fixture,16,1); struct.pack_into('<II',fixture,32,0x19,152)
        struct.pack_into('<I',fixture,96,1); fixture[104:110]=b'__text'
        struct.pack_into('<Q',fixture,144,4); struct.pack_into('<I',fixture,152,224)
        fixture[224:228]=b'test'
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp); executable=app/'Contents/MacOS/Wizard'; executable.parent.mkdir(parents=True)
            executable.write_bytes(fixture)
            self.assertEqual(identity.release_digest(app,'Contents/MacOS/Wizard'),identity.sha(b'test'))
            fixture[-4:]=b'sign'; executable.write_bytes(fixture)
            self.assertEqual(identity.release_digest(app,'Contents/MacOS/Wizard'),identity.sha(b'test'))

    def test_approved_dark_pixels_and_exact_icns(self):
        identity.verify_sources()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'Wizard.icns'
            identity.icon.pack(identity.ASSETS,out,dark=True)
            chunks=identity.verify_icns(out.read_bytes())
            self.assertEqual(len(chunks),10)
            self.assertTrue(all(x['corner']==[11,10,16,255] for x in chunks))
            # Negative: a stale (perfectly valid) purple ICNS must fail.
            identity.icon.pack(identity.ASSETS,out)
            with self.assertRaises(AssertionError): identity.verify_icns(out.read_bytes())

    def test_actual_plist_recipe_names_and_ids(self):
        recipe=(MAC/'build.sh').read_text()
        # Execute the production plist function and call sites, without compiler,
        # framework, codesign, DMG or external effects. This is fixture evidence.
        fragment=recipe[recipe.index('plist() {'):recipe.index('# Public metadata only.')]
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp)/'WizardOS.app'; host=app/identity.HOST
            for bundle in (app,host): (bundle/'Contents').mkdir(parents=True)
            subprocess.run(['/bin/bash','-eu','-c',fragment],check=True,
                           env=dict(APP=str(app),HOST=str(host),VER='0.7.2',BUILD='99991'))
            for bundle,name,bid,exe in ((app,'WizardOS',identity.APP_ID,'Wizard'),(host,'WizardOS Host',identity.HOST_ID,'Wizard Host')):
                info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
                self.assertEqual(info['CFBundleName'],name)
                self.assertEqual(info['CFBundleDisplayName'],name)
                self.assertEqual(info['CFBundleIdentifier'],bid)
                self.assertEqual(info['CFBundleExecutable'],exe)
                self.assertEqual(info['CFBundleIconFile'],'Wizard')
        for expected in ['APP=$OUT/WizardOS.app','"$STAGE/WizardOS.app"','--dark','cp assets/brand/dark/provenance.json']:
            self.assertIn(expected,recipe)
        self.assertNotIn('Wizard MVP.app',recipe)

    def test_continuity_and_path_independent_watchdog(self):
        shared=(MAC/'Shared/Shared.swift').read_text()
        self.assertIn('static let appBundleID = "org.humanitylabs.wizard.mvp"',shared)
        self.assertIn('static let hostBundleID = "org.humanitylabs.wizard.mvp.host"',shared)
        self.assertIn('return base.appendingPathComponent("Wizard MVP", isDirectory: true)',shared)
        self.assertIn('defaults?.string(forKey: "DataHome")',shared)
        # Preserve selected/default Files, saved-state IDs and updater protocol.
        self.assertIn('.appendingPathComponent("Wizard MVP", isDirectory: true)',shared)
        release=(MAC/'Shared/UpdateContract.swift').read_text()
        self.assertIn('Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host',release)
        host=(MAC/'Host/main.swift').read_text()
        capture=host[host.index('let missingAppWatch ='):host.index('private let diskOwnership')]
        self.assertIn('Bundle.main.bundleURL',capture)
        self.assertEqual(capture.count('.deletingLastPathComponent()'),4)
        self.assertNotIn('Wizard.app',capture)
        native=(MAC/'App/WizardRemoval.swift').read_text()
        self.assertIn('Bundle.main.bundleURL',native)
        self.assertNotIn('/Applications/Wizard.app',native)
        app=(MAC/'App/main.swift').read_text()
        self.assertNotIn('under Wizard MVP',app)
        self.assertIn('window.title = "WizardOS"',app)
        self.assertIn('SMAppService.loginItem(identifier: WizardShared.hostBundleID)',native)

    def test_required_resources_are_mandatory(self):
        recipe=(MAC/'build.sh').read_text()
        for text in ['for bundle in "$APP" "$HOST"','Wizard.icns','wizard-mark-{purple,white}.png','WizardBrandProvenance.json','wizard-release.json','bring-hermes/wizard-bring-hermes','Sparkle.framework']:
            self.assertIn(text,recipe)
        self.assertNotIn('if [[ -f assets/Wizard.icns',recipe)


if __name__=='__main__': unittest.main(verbosity=2)
