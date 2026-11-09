#!/usr/bin/env python3
"""Wizard for Mac launches on macOS 14, as its 14.0 minimum promises.

0.7.0 crashed at launch on macOS 14.3: dyld couldn't find the Swift overlay initializer
`CATapDescription(excludingProcesses:deviceUID:stream:)`, which the SDK labels macOS 14.0 but
which only exists in libswiftCoreAudio from macOS 15. Meeting audio now uses the Objective-C
initializer, and the build stops if a binary links a CATapDescription overlay symbol as required.
"""
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
CAPTURE = MAC / 'App/MeetingCapture.swift'
BUILD = MAC / 'build.sh'
CHECK = MAC / 'check-launch-symbols.py'

# `nm -m` lines as printed for the 0.7.0/0.8.0 app binary.
BAD_IMPORT = ('                 (undefined) external _$sSo16CATapDescriptionC9CoreAudioE18excludingProcesses9deviceUID6stream'
              'ABSays6UInt32VG_SSSutcfC (from libswiftCoreAudio)')
WEAK_IMPORT = '                 (undefined) weak external _AudioHardwareCreateProcessTap (from CoreAudio)'
OBJC_IMPORT = '                 (undefined) external _objc_msgSend$initExcludingProcesses:andDeviceUID:withStream:'


def load_check():
    spec = importlib.util.spec_from_file_location('check_launch_symbols', CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MacOS14LaunchTests(unittest.TestCase):
    def test_tap_uses_objc_initializers_only(self):
        src = re.sub(r'//.*', '', CAPTURE.read_text())  # code only; comments may name the overlay API
        calls = re.findall(r'CATapDescription\(\s*(\w*)\s*:', src)
        self.assertTrue(calls, 'meeting capture should still build a CATapDescription')
        self.assertEqual([c for c in calls if not c.startswith('__')], [],
                         'Swift overlay CATapDescription initializers are missing on macOS 14; use the __ (Objective-C) ones')
        self.assertIn('CATapDescription(__excludingProcesses:', src)

    def test_check_flags_required_overlay_symbol(self):
        found = load_check().violations('\n'.join([BAD_IMPORT, WEAK_IMPORT, OBJC_IMPORT]))
        self.assertEqual(len(found), 1)
        self.assertIn('excludingProcesses', found[0][0])
        self.assertEqual(found[0][1], 'libswiftCoreAudio')

    def test_check_allows_weak_and_objc_imports(self):
        self.assertEqual(load_check().violations('\n'.join([WEAK_IMPORT, OBJC_IMPORT])), [])
        weak_overlay = BAD_IMPORT.replace('(undefined) external', '(undefined) weak external')
        self.assertEqual(load_check().violations(weak_overlay), [])

    def test_build_runs_the_check_on_both_binaries(self):
        build = BUILD.read_text()
        app_link = build.find('-o "$APP/Contents/MacOS/Wizard"')
        check = build.find('python3 check-launch-symbols.py "$APP/Contents/MacOS/Wizard" "$HOST/Contents/MacOS/Wizard Host"')
        self.assertGreater(app_link, 0)
        self.assertGreater(check, app_link, 'the check must run right after both binaries are linked')
        self.assertLess(check, build.find('codesign'), 'and before anything is signed or packaged')

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'needs the macOS SDK')
    def test_objc_initializer_links_no_overlay_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'tap.swift'
            src.write_text('import CoreAudio\nimport Foundation\n@available(macOS 14.2, *)\n'
                           'func tap(_ me: [AudioObjectID], _ uid: String) -> CATapDescription {\n'
                           '    CATapDescription(__excludingProcesses: me.map { NSNumber(value: $0) }, andDeviceUID: uid, withStream: 0)\n}\n')
            obj = Path(tmp) / 'tap.o'
            subprocess.run(['xcrun', 'swiftc', '-O', '-target', 'arm64-apple-macos14.0', '-swift-version', '5',
                            '-c', str(src), '-o', str(obj)], check=True, capture_output=True)
            out = subprocess.run(['xcrun', 'nm', '-m', str(obj)], check=True, capture_output=True, text=True).stdout
            self.assertEqual(load_check().violations(out), [])
            self.assertIn('initExcludingProcesses:andDeviceUID:withStream:', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
