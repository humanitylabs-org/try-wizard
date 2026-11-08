#!/usr/bin/env python3
"""The Mac shell tells Wizard UX how much room the window buttons take (issue #19).

The main window has a transparent full-size title bar, so the red/yellow/green buttons float over the top-left of
the page. Wizard UX reserves `--wz-titlebar-left` before the desktop bar's content (a fixed 96px when it is unset).
The native shell sets that variable from where the window buttons really end, in page (CSS) pixels: it follows page
zoom, and it is 0 in full screen, where the buttons are hidden. Off by default, behind `TitleBarDoubleClick`.
CI does not compile App/main.swift, so this is a source contract.
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


class TitlebarInsetTests(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text()
        self.inset = block(self.src, 'enum WizardTitleBarInset', '// MARK: - Zoom')
        self.publish = block(self.src, 'func publishTitleBarInset()', 'func updateDragRegions')
        self.app = block(self.src, 'final class AppDelegate', '@objc func switchBackend')

    def test_sets_the_css_variable_wizard_ux_reads(self):
        self.assertIn("document.documentElement.style.setProperty('--wz-titlebar-left','\\(left)px')", self.inset)
        self.assertIn('web.evaluateJavaScript(WizardTitleBarInset.script(left: left))', self.publish)

    def test_measures_the_real_window_buttons(self):
        for button in ('.closeButton', '.miniaturizeButton', '.zoomButton'):
            self.assertIn(button, self.publish)
        self.assertIn('window.standardWindowButton($0)', self.publish)
        self.assertIn('convert($0.bounds, to: nil).maxX', self.publish)

    def test_follows_zoom_and_full_screen(self):
        fn = block(self.inset, 'static func cssLeft(', 'static func script')
        self.assertRegex(fn, r'if fullScreen \|\| buttonsMaxX <= 0 \{ return 0 \}')
        self.assertIn('((buttonsMaxX + gap) / zoom).rounded(.up)', fn)
        self.assertIn('fullScreen: window.styleMask.contains(.fullScreen)', self.publish)
        self.assertIn('pageZoom: web.pageZoom', self.publish)

    def test_switch_is_off_by_default_and_only_for_wizard_pages(self):
        self.assertRegex(self.publish, r'guard WizardTitleBarDoubleClick\.isOn, isTrustedDocument, let window else \{ return \}')

    def test_republished_when_the_room_changes(self):
        finish = block(self.src, 'func webView(_ webView: WKWebView, didFinish navigation', '// Landed on the legacy')
        self.assertIn('publishTitleBarInset()', finish)
        for hook in ('func windowDidResize', 'func windowDidEnterFullScreen', 'func windowDidExitFullScreen',
                     'func setWizardZoom'):
            body = block(self.app, hook, '\n' if 'FullScreen' in hook else '\n    }\n')
            self.assertIn('publishTitleBarInset()', body, hook)


class InsetMathTests(unittest.TestCase):
    """Mirror of WizardTitleBarInset.cssLeft, so the numbers Wizard UX gets are pinned."""

    @staticmethod
    def css_left(max_x, zoom, full_screen, gap=12):
        import math
        if full_screen or max_x <= 0:
            return 0
        return math.ceil((max_x + gap) / (zoom if zoom > 0 else 1))

    def test_gap_constant_matches(self):
        self.assertRegex(MAIN.read_text(), r'static let gap: CGFloat = 12\n')

    def test_values(self):
        self.assertEqual(self.css_left(72, 1, False), 84)     # usual buttons, 100%
        self.assertEqual(self.css_left(72, 2, False), 42)     # zoomed in: fewer CSS px cover the same points
        self.assertEqual(self.css_left(72, 0.5, False), 168)  # zoomed out: more CSS px
        self.assertEqual(self.css_left(72, 1, True), 0)       # full screen hides the buttons


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
