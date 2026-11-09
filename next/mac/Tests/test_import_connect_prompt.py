#!/usr/bin/env python3
"""Bring My Hermes asks the owner to connect Claude or ChatGPT when neither is connected (try-wizard#51).

Source contract for next/mac/App/main.swift (CI doesn't compile the Mac app). The prompt ships off by default
behind the `ImportConnectPrompt` user default, and only an explicit `ai_connected: false` from the importer asks.
"""
import re
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / 'App/main.swift'


def block(source: str, start: str, end: str) -> str:
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError('%r not found in App/main.swift' % start)
    return source[i:j]


class ImportConnectPromptTests(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text()
        self.enum = block(self.src, 'enum WizardImportConnectPrompt', '/// Double-click on the blank top bar')
        self.bring = block(self.src, '@objc func bringHermes()', '@objc func restartLocal()')

    def test_switch_is_off_by_default(self):
        self.assertIn('static let key = "ImportConnectPrompt"', self.enum)
        self.assertRegex(self.enum, r'static var isOn: Bool \{ UserDefaults\.standard\.bool\(forKey: key\) \}')
        self.assertRegex(self.enum, r'guard isOn, let connected = result\?\["ai_connected"\] as\? Bool else \{ return false \}')
        self.assertIn('return connected == false', self.enum)

    def test_dialog_asks_only_when_needed_and_offers_both_apps(self):
        self.assertIn('if WizardImportConnectPrompt.needed(obj) {', self.bring)
        self.assertIn('"Connect Claude or ChatGPT so it can answer."', self.enum)
        self.assertIn('("Connect Claude", "wizard-claude")', self.enum)
        self.assertIn('("Connect ChatGPT", "wizard-chatgpt")', self.enum)
        self.assertIn('done.addButton(withTitle: "Later")', self.bring)
        # the prompt is part of the success branch only
        ok = self.bring.index('obj?["ok"] as? Bool == true')
        fail = self.bring.index('"Wizard couldn\'t bring your Hermes in"')
        self.assertTrue(ok < self.bring.index('WizardImportConnectPrompt.needed(obj)') < fail)

    def test_pressed_button_opens_that_app_after_the_reload(self):
        self.assertIn('let choice = askedToConnect ? WizardImportConnectPrompt.appId(for: response) : nil', self.bring)
        after = self.bring[self.bring.index('self.controller.begin()'):]
        self.assertIn('if let appId = choice { self.openWizardAppWhenReady(appId) }', after)
        self.assertIn('self.controller.uxState', self.bring)
        self.assertIn('evaluateJavaScript(WizardImportConnectPrompt.openScript(appId))', self.bring)

    def test_open_script_uses_the_shell_and_only_known_apps(self):
        self.assertIn('guard choices.contains(where: { $0.1 == appId }) else { return "false" }', self.enum)
        self.assertIn("window.WizOpenApp", self.enum)
        self.assertIn("/wizard-os-home/store/index.html?app=", self.enum)

    def test_later_opens_nothing(self):
        fn = block(self.enum, 'static func appId(for response', 'static func openScript')
        self.assertIn('index < choices.count', fn)
        self.assertTrue(re.search(r'guard index >= 0, index < choices\.count else \{ return nil \}', fn))


if __name__ == '__main__':
    unittest.main()
