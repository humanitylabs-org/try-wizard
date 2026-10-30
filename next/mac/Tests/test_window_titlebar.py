#!/usr/bin/env python3
"""The main window draws Wizard's own top bar in the title-bar area, so the system title must stay hidden.

The window uses a transparent full-size title bar: Wizard UX's top bar (Home, desktops, clock) sits right of the
traffic lights. A visible window title is drawn there too, on top of the Home button. The title itself stays set,
because Mission Control and the Window menu still name the window.
"""
import re
import sys
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / 'App/main.swift'


def main_window_setup(source: str) -> str:
    """The statements that configure the main NSWindow, from its creation to super.init(window:)."""
    start = source.find('let window = NSWindow(')
    end = source.find('super.init(window: window)', start)
    if start < 0 or end < 0:
        raise AssertionError('main window setup not found in App/main.swift')
    return source[start:end]


class WindowTitlebarTests(unittest.TestCase):
    def setUp(self):
        self.setup = main_window_setup(MAIN.read_text())

    def test_web_content_fills_the_title_bar(self):
        self.assertIn('.fullSizeContentView', self.setup)
        self.assertRegex(self.setup, r'window\.titlebarAppearsTransparent\s*=\s*true')

    def test_system_title_is_not_drawn_over_the_top_bar(self):
        self.assertRegex(self.setup, r'window\.titleVisibility\s*=\s*\.hidden',
                         'a visible window title draws "Wizard" over the top bar\'s Home button')

    def test_window_keeps_its_name(self):
        self.assertRegex(self.setup, r'window\.title\s*=\s*"Wizard"')


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
