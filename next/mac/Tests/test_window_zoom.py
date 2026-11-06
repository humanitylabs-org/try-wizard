#!/usr/bin/env python3
"""The Mac app zooms like every Mac app: View › Zoom In (⌘+ / ⌘=), Zoom Out (⌘−), Actual Size (⌘0).

WKWebView has no zoom of its own, so without these items ⌘− does nothing and a laptop screen can't fit more.
The zoom is kept across launches and restored when the window opens.
"""
import re
import sys
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / 'App/main.swift'


class ZoomTests(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text()
        start = self.src.find('let view = NSMenu(title: "View")')
        self.view = self.src[start:self.src.find('viewItem.submenu = view', start)]

    def test_view_menu_has_standard_zoom_items(self):
        for title, key, action in [('Actual Size', '0', 'zoomWizardReset'), ('Zoom In', '+', 'zoomWizardIn'),
                                   ('Zoom In', '=', 'zoomWizardIn'), ('Zoom Out', '-', 'zoomWizardOut')]:
            self.assertRegex(self.view, r'addItem\(withTitle: "%s", action: #selector\(%s\(_:\)\), keyEquivalent: "%s"\)\.target = self'
                             % (re.escape(title), action, re.escape(key)))

    def test_hidden_equals_shortcut_remains_eligible_for_key_matching(self):
        start = self.view.index('keyEquivalent: "="')
        alias = self.view[start:self.view.index('withTitle: "Zoom Out"', start)]
        self.assertIn('view.items.last?.isHidden = true', alias)
        self.assertIn('view.items.last?.allowsKeyEquivalentWhenHidden = true', alias)

    def test_zoom_sets_page_zoom_and_is_saved(self):
        body = self.src[self.src.find('func setWizardZoom'):]
        body = body[:body.find('}')]
        self.assertIn('controller.web.pageZoom = zoom', body)
        self.assertIn('WizardZoom.saved = zoom', body)

    def test_saved_zoom_is_restored_on_the_main_web_view(self):
        self.assertRegex(self.src, r'web\.pageZoom = WizardZoom\.saved')

    def test_steps_include_actual_size_and_are_sorted(self):
        m = re.search(r'static let steps: \[CGFloat\] = \[([^\]]+)\]', self.src)
        steps = [float(x) for x in m.group(1).split(',')]
        self.assertEqual(steps, sorted(steps))
        self.assertIn(1.0, steps)
        self.assertLessEqual(steps[0], 0.5)


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
