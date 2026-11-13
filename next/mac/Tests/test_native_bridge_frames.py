#!/usr/bin/env python3
"""Native page→Mac authority is main-document-only and bound to the document that asked (wizard-os issue 387).

WKUserContentController.add(_:name:) exposes window.webkit.messageHandlers.wizardNative to EVERY frame, so the
receiver itself must admit only the trusted main frame, and a reply must never reach a different document than the one
that asked (a reload or same-origin navigation while native work is in flight). This is a source contract; the real
WebKit proof is the QAHooks receipt on a Mac (qa-native-drag-authority.py records mainFrame/admitted per message).
"""
import re
import sys
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / 'App/main.swift'


def between(source: str, start: str, end: str) -> str:
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError(f'{start!r} not found in App/main.swift')
    return source[i:j]


class NativeBridgeFrameTests(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text()

    def test_one_message_handler_in_the_page_world_only(self):
        self.assertEqual(len(re.findall(r'userContentController\.add\(', self.src)), 1)
        self.assertNotIn('addScriptMessageHandler', self.src, 'reply handlers / other content worlds need the same review')
        self.assertNotIn('WKContentWorld', self.src)

    def test_injected_scripts_are_main_frame_only(self):
        scripts = re.findall(r'WKUserScript\(([^)]*)\)', self.src)
        self.assertTrue(scripts)
        for s in scripts:
            self.assertIn('forMainFrameOnly: true', s)

    def test_receiver_admits_only_the_trusted_main_frame(self):
        allows = between(self.src, 'func allowsNative(_ frame: WKFrameInfo) -> Bool {', '\n    }')
        self.assertIn('frame.isMainFrame', allows)
        self.assertIn('isTrustedDocument', allows)
        self.assertIn('selectedControlOrigins.contains(origin)', allows)
        receive = between(self.src, 'didReceive message: WKScriptMessage) {', 'handler(method, params)')
        self.assertIn('owner?.allowsNative(message.frameInfo) == true', receive)
        self.assertIn('guard admitted else { return }', receive)

    def test_replies_are_bound_to_the_asking_document(self):
        receive = between(self.src, 'didReceive message: WKScriptMessage) {', '\n// MARK: - Local voice')
        self.assertIn('let generation = owner?.documentGeneration', receive)
        self.assertRegex(receive, r'generation != nil, self\?\.owner\?\.documentGeneration == generation')
        commit = between(self.src, 'didCommit navigation: WKNavigation!) {', '\n    }')
        self.assertIn('documentGeneration &+= 1', commit)

    def test_media_permission_uses_the_same_frame_admission(self):
        media = between(self.src, 'requestMediaCapturePermissionFor origin: WKSecurityOrigin', 'decisionHandler(allowed')
        self.assertIn('allowsNative(frame)', media)


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
