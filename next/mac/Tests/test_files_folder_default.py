#!/usr/bin/env python3
"""The suggested shared folder is outside macOS's protected folders (issue #103).

Owner report: on a fresh Mac install, tapping "Use This Folder" made macOS ask "Wizard.app would like to access
files in your Documents folder", which reads as access to all of Documents. The suggestion was ~/Documents/Wizard MVP.
It is now ~/Wizard (home folder, not TCC-protected), so a default install shows no Documents prompt. A saved
files-folder.json is never rewritten, so existing installs keep their folder. CI does not compile the App target,
so this checks the source.
"""
import re
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def default_folder_body():
    src = (MAC / 'Shared/Shared.swift').read_text()
    m = re.search(r'static var defaultFilesFolder: URL \{(.*?)\n    \}', src, re.S)
    assert m, 'defaultFilesFolder not found'
    return m.group(1)


class FilesFolderDefaultTests(unittest.TestCase):
    def test_default_is_home_wizard(self):
        body = default_folder_body()
        self.assertIn('homeDirectoryForCurrentUser', body)
        self.assertIn('appendingPathComponent("Wizard", isDirectory: true)', body)

    def test_default_is_not_in_a_protected_folder(self):
        body = default_folder_body()
        for protected in ('documentDirectory', 'desktopDirectory', 'downloadsDirectory', 'Documents', 'Desktop', 'Downloads'):
            self.assertNotIn(protected, body)

    def test_saved_choice_still_wins(self):
        src = (MAC / 'Shared/Shared.swift').read_text()
        self.assertIn('static var filesFolderFile: URL { supportDir.appendingPathComponent("files-folder.json") }', src)
        main = (MAC / 'App/main.swift').read_text()
        self.assertIn('WizardShared.filesFolder ?? WizardShared.defaultFilesFolder', main)
        # Only the first-run chooser and explicit actions write the default; launching never rewrites a saved folder.
        self.assertNotRegex(main, r'WizardShared\.setFilesFolder\(WizardShared\.defaultFilesFolder\)')


if __name__ == '__main__':
    unittest.main()
