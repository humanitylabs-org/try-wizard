#!/usr/bin/env python3
"""The Mac app spells the product name WizardOS, one word, always (James, 8 Nov 2026; wizard-os#436).

Only text people read changes; ids, paths, URLs and log lines keep their names.
"""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
TWO = 'Wizard' + ' OS'  # the two-word spelling, built so this file never contains it
LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')

# Files whose visible strings follow the switch. UpdateContract.swift and WizardGuestActivation.swift are also
# compiled alone by the Mac admission/activation harnesses (without Brand.swift), so they keep their text for now.
SWITCHED = ['App/main.swift', 'App/WizardKeys.swift', 'App/WizardBackup.swift', 'App/WizardUpdater.swift']


def visible_literals(path: Path, start: "str | None" = None):
    src = path.read_text()
    if start:
        src = src[src.index(start):]
    for n, line in enumerate(src.split('\n'), 1):
        s = line.lstrip()
        if s.startswith('//') or 'log(' in line:
            continue
        for lit in LITERAL.findall(line):
            yield n, lit


class WizardOSNameTests(unittest.TestCase):
    def setUp(self):
        self.brand = (MAC / 'Shared/Brand.swift').read_text()
        self.name = self.brand[self.brand.index('enum WizardOSName'):]

    def test_name_is_always_one_word(self):
        self.assertIn('static var text: String { "WizardOS" }', self.name)
        self.assertNotIn('isOn', self.name)
        self.assertNotIn(TWO, self.brand)
        # Source contract only: the final name enum has no trailing declaration/brace.
        self.assertRegex(self.name, r'\Aenum WizardOSName\s*\{\s*static var text: String \{ "WizardOS" \}\s*\}\s*\Z')

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'),
                         'Brand.swift syntax parse requires macOS and swiftc')
    def test_brand_swift_syntax(self):
        # Parse the real source, without compiling/linking the native app.
        result = subprocess.run(['swiftc', '-frontend', '-parse', str(MAC / 'Shared/Brand.swift')],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_both_targets_compile_the_name(self):
        build = (MAC / 'build.sh').read_text()
        targets = [l for l in build.split('\n') if 'SWIFTC[@]' in l and '-o ' in l]
        self.assertEqual(len(targets), 2)
        for line in targets:
            self.assertIn('Shared/Brand.swift', line)

    def test_visible_strings_follow_the_switch(self):
        for name in SWITCHED:
            left = [(n, lit) for n, lit in visible_literals(MAC / name) if TWO in lit]
            self.assertEqual(left, [], '%s still hard-codes the two-word name' % name)
        left = [(n, lit) for n, lit in visible_literals(MAC / 'Host/main.swift', '// MARK: - Menu bar')
                if TWO in lit]
        self.assertEqual(left, [], 'Wizard Host menu still hard-codes the two-word name')

    def test_menus_and_install_screens_use_the_name(self):
        main = (MAC / 'App/main.swift').read_text()
        for text in ('"Get \\(WizardOSName.text)"', '"Download \\(WizardOSName.text)"',
                     '"Install \\(WizardOSName.text) from File…"', '"\\(WizardOSName.text) didn\'t start"'):
            self.assertIn(text, main)
        # The corrupt-file check matches the error it built, whichever name is on.
        self.assertIn('contains("valid \\(WizardOSName.text)")', main)
        self.assertIn('"This file isn\'t a valid \\(WizardOSName.text) image.', main)
        keys = (MAC / 'App/WizardKeys.swift').read_text()
        self.assertIn('"Restart \\(WizardOSName.text)"', keys)
        host = (MAC / 'Host/main.swift').read_text()
        self.assertIn('"Quit Wizard (stops \\(WizardOSName.text))"', host)

    def test_ids_and_bundle_names_unchanged(self):
        build = (MAC / 'build.sh').read_text()
        self.assertIn('"Wizard MVP" org.humanitylabs.wizard.mvp Wizard', build)
        self.assertIn('"Wizard Host" org.humanitylabs.wizard.mvp.host', build)


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
