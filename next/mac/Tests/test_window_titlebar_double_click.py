#!/usr/bin/env python3
"""Double-clicking blank space in Wizard's top bar acts like a native Mac title bar (issue #19).

The main window has a transparent full-size title bar, so Wizard UX's bar is the title bar, and the native
WizardDragView moves the window from its blank space. A double-click there must do what System Settings ›
Desktop & Dock › "Double-click a window's title bar to" says: zoom (Fill/Zoom, the default), minimize or nothing.
It ships off by default behind the `TitleBarDoubleClick` user default.
"""
import re
import sys
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / 'App/main.swift'


def block(source: str, start: str, end: str) -> str:
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError('%r not found in App/main.swift' % start)
    return source[i:j]


class TitlebarDoubleClickTests(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text()
        self.mouse_down = block(self.src, 'override func mouseDown(with event: NSEvent)', 'static let script')
        self.dbl = block(self.src, 'enum WizardTitleBarDoubleClick', '// MARK: - Zoom')

    def test_double_click_on_blank_bar_runs_the_system_action_before_dragging(self):
        self.assertIn('event.clickCount == 2', self.mouse_down,
                      'double-clicking the top bar does nothing: the drag view never looks at clickCount')
        check = self.mouse_down.find('event.clickCount == 2')
        self.assertLess(check, self.mouse_down.find('dragCount += 1'), 'a double-click must not start a drag')
        self.assertRegex(self.mouse_down, r'WizardTitleBarDoubleClick\.perform\(on: window\); return')

    def test_switch_is_off_by_default(self):
        self.assertIn('static let key = "TitleBarDoubleClick"', self.dbl)
        self.assertRegex(self.dbl, r'static var isOn: Bool \{ UserDefaults\.standard\.bool\(forKey: key\) \}')
        self.assertRegex(self.mouse_down, r'clickCount == 2, WizardTitleBarDoubleClick\.isOn')

    def test_follows_the_system_double_click_setting(self):
        self.assertIn('"AppleActionOnDoubleClick"', self.dbl)
        self.assertIn('"AppleMiniaturizeOnDoubleClick"', self.dbl)
        self.assertIn('window.performZoom(nil)', self.dbl)
        self.assertIn('window.performMiniaturize(nil)', self.dbl)

    def test_action_mapping(self):
        fn = block(self.dbl, 'static func action(', 'static func perform')
        cases = dict(re.findall(r'case ([^:]+): return \.(\w+)', fn))
        self.assertEqual(cases.get('"Minimize"'), 'minimize')
        self.assertEqual(cases.get('"None"'), 'none')
        self.assertEqual(cases.get('"Fill", "Maximize"'), 'zoom')
        self.assertRegex(fn, r'default: return legacyMinimize \? \.minimize : \.zoom')


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
