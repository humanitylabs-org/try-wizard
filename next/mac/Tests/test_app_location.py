#!/usr/bin/env python3
"""Maps may use the Mac's location after macOS's own prompt; nobody else can (try-wizard#135, wizard-ux#1629).

Off by default behind the `AppLocation` user default. The rules live in Shared/AppLocation.swift (XCTest in
Tests/AppLocation, run by `swift test` on macOS CI); this checks the wiring from source on any machine.
"""
import re
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def block(source: str, start: str, end: str) -> str:
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError('%r not found' % start)
    return source[i:j]


class AppLocationTests(unittest.TestCase):
    def setUp(self):
        self.main = (MAC / 'App/main.swift').read_text()
        self.build = (MAC / 'build.sh').read_text()
        self.rule = (MAC / 'Shared/AppLocation.swift').read_text()

    def test_switch_is_off_by_default(self):
        body = block(self.main, 'enum WizardAppLocation {', '\n}\n')
        self.assertIn('static let key = "AppLocation"', body)
        self.assertRegex(body, r'static var isOn: Bool \{ UserDefaults\.standard\.bool\(forKey: key\) \}')
        self.assertIn('defaults write org.humanitylabs.wizard.mvp AppLocation -bool YES', self.main)

    def test_webkit_geolocation_question_is_answered_through_the_rule(self):
        self.assertIn('@objc(_webView:requestGeolocationPermissionForOrigin:initiatedByFrame:decisionHandler:)', self.main)
        self.assertIn('@objc(_webView:requestGeolocationPermissionForFrame:decisionHandler:)', self.main)
        decide = block(self.main, 'private func decideLocation(', '\n    }\n')
        self.assertIn('switchOn: on', decide)
        self.assertIn('trustedShell: isTrustedDocument', decide)
        self.assertIn('wizardLocationOrigins.contains', decide)
        self.assertIn('locationConsent.ask', decide)
        self.assertIn('afterPrompt($0) == .grant', decide)
        # With the switch off the app never touches CoreLocation.
        self.assertIn('on ? locationConsent.access : .refused', decide)
        self.assertIn('private lazy var locationConsent', self.main)

    def test_only_wizard_addresses(self):
        origins = block(self.main, 'private var wizardLocationOrigins', '\n    }\n')
        self.assertIn('selectedControlOrigins', origins)
        self.assertIn('.thisMac', origins)
        self.assertIn('NativeOrigin(scheme: "http", host: "localhost", port: Int(WizardShared.uxPort))', self.main)

    def test_rule_grants_only_after_a_yes(self):
        self.assertIn('guard switchOn, trustedShell, wizardAddress else { return .deny }', self.rule)
        self.assertIn('case .refused: return .deny', self.rule)
        self.assertIn("access == .allowed ? .grant : .deny", self.rule)

    def test_bundle_declares_location_use(self):
        self.assertIn('<key>NSLocationWhenInUseUsageDescription</key>', self.build)
        self.assertIn('<key>NSLocationUsageDescription</key>', self.build)
        self.assertIn('<key>com.apple.security.personal-information.location</key><true/>', self.build)
        self.assertIn('-framework CoreLocation', self.build)
        self.assertIn('Shared/AppLocation.swift Shared/HostHandover.swift', self.build)
        self.assertIn('"AppLocation.swift"', (MAC / 'Package.swift').read_text())
        self.assertTrue((MAC / 'Tests/AppLocation/AppLocationTests.swift').exists())


if __name__ == '__main__':
    unittest.main()
