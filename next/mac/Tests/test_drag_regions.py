#!/usr/bin/env python3
"""try-wizard#160: the Mac title-bar drag strip takes a click only on blank top-bar space.

The page reports its top bar and every control reaching into it (Shared/DragRegions.swift `script`, anywhere on the
page, not only inside #bar), reports an empty strip when the bar is hidden (full screen), and the window scales the
report by the page zoom. These checks keep main.swift wired to that one rule. The rule itself is tested by
Tests/DragRegions (swift test) and was run in Chromium against the real wizard-ux shell (see the PR).
"""
import re
import sys
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
MAIN = (MAC / 'App/main.swift').read_text()
SHARED = (MAC / 'Shared/DragRegions.swift').read_text()
BUILD = (MAC / 'build.sh').read_text()
PACKAGE = (MAC / 'Package.swift').read_text()


def block(src, start, end):
    a = src.index(start)
    return src[a:src.index(end, a)]


class DragRegionsWiring(unittest.TestCase):
    def test_hit_test_asks_the_shared_rule_with_the_page_zoom(self):
        hit = block(MAIN, 'override func hitTest(_ point: NSPoint)', 'override func mouseDown')
        self.assertIn('WizardDragRegions.inWindowButtons(p)', hit)
        self.assertIn('WizardDragRegions.drags(regions, at: p, pageZoom: owner.web.pageZoom, viewSize: bounds.size)', hit)
        self.assertNotIn('controls.contains', hit, 'the old unscaled check is gone')

    def test_the_injected_script_is_the_shared_one(self):
        self.assertIn('static let script = WizardDragRegions.script', MAIN)
        self.assertIn('WKUserScript(source: WizardDragView.script, injectionTime: .atDocumentStart, forMainFrameOnly: true)', MAIN)

    def test_reports_go_through_parse(self):
        upd = block(MAIN, 'func updateDragRegions(', '\n    }\n')
        self.assertIn('WizardDragRegions.parse(params)', upd)
        self.assertNotIn('prefix(100)', MAIN)

    def test_script_reports_page_controls_and_hidden_bars(self):
        self.assertIn("document.querySelectorAll(PAGE)", SHARED)
        self.assertIn("hidden ? [0,0,0,0]", SHARED)
        self.assertIn("addEventListener('pointermove',near", SHARED)
        self.assertNotIn('requestAnimationFrame', SHARED, 'RAF stops while the window is hidden')

    def test_built_and_tested(self):
        app_line = next(l for l in BUILD.splitlines() if 'App/main.swift' in l and '"$APP/' in l)
        self.assertIn('Shared/DragRegions.swift', app_line)
        self.assertRegex(PACKAGE, r'name: "WizardDragRegions".*sources: \["DragRegions.swift"\]')
        self.assertTrue((MAC / 'Tests/DragRegions/DragRegionsTests.swift').exists())


if __name__ == '__main__':
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
