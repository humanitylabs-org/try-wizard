#!/usr/bin/env python3
"""wizard-os#133: the Mac app's own calls to a Wizard's owner routes work with the browser boundary on.

With the boundary on, the Agent Service answers an owner route only with the shell-only token (401
shell_token_required otherwise). The Mac window's shell gets it from its page load; the app's native calls did not:
dictation (POST /wizard/voice/transcribe) failed, and the Host's update lease (POST /wizard/v1/maintenance) got 401
instead of the 404 that sends a standard guest to its own idle check, so every Mac app update waited forever.

The Swift is unit-tested by CI (`swift test`, Tests/ShellToken). These checks pin the wiring and the guest marker that
tells the App Manager this Mac app is ready (wizard-app-manager wam/browser_boundary.py mac_guest).
"""
import json
import re
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
ROOT = MAC.parents[1]


def block(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i + len(start))]


class MacShellToken(unittest.TestCase):
    def test_dictation_sends_through_the_token_carrier(self):
        ui = (MAC / 'App/MeetingUI.swift').read_text()
        t = block(ui, '    func transcribe(_ wav: Data', '    static func insert(')
        self.assertIn('WizardShellToken.send(req) {', t)
        self.assertNotIn('URLSession.shared.dataTask', t)

    def test_token_reader_is_compiled_into_the_app(self):
        build = (MAC / 'build.sh').read_text()
        app = next(line for line in build.splitlines() if 'App/main.swift' in line and '"$APP/Contents/MacOS/Wizard"' in line)
        self.assertIn('Shared/ShellToken.swift', app)
        pkg = (MAC / 'Package.swift').read_text()
        self.assertIn('sources: ["ShellToken.swift"]', pkg)
        self.assertIn('path: "Tests/ShellToken"', pkg)

    def test_token_stays_in_memory_and_on_its_own_origin(self):
        src = (MAC / 'Shared/ShellToken.swift').read_text()
        code = '\n'.join(line for line in src.splitlines() if not line.strip().startswith('///'))
        for never in ('UserDefaults', 'FileManager', 'write(to', 'print(', 'NSLog', 'log('):
            self.assertNotIn(never, code)
        # Read only from that origin's own shell page, as a top-level page load (what nginx writes the token for).
        self.assertIn('originKey(http?.url) == key', code)
        self.assertIn('"Sec-Fetch-Mode"', code)
        self.assertIn('"Sec-Fetch-Dest"', code)
        self.assertIn('[0-9a-f]{64}', code)
        # Retried once, and only for the boundary's own refusal.
        self.assertIn('j["error"] as? String == "shell_token_required"', code)
        self.assertIn('guard let token, token != had', code)

    def test_page_marker_matches_the_shell(self):
        # wizard-ux web/index.html ships exactly this meta; nginx swaps `off` for the token on a page load.
        src = (MAC / 'Shared/ShellToken.swift').read_text()
        found = re.search(r'NSRegularExpression\(pattern: "(.*?)"\)', src)
        assert found is not None
        pattern = found.group(1).encode().decode('unicode_escape')
        page = '<meta name="wizard-shell-token" content="%s">' % ('0f' * 32)
        hit = re.search(pattern, page)
        assert hit is not None
        self.assertEqual(hit.group(1), '0f' * 32)
        self.assertIsNone(re.search(pattern, '<meta name="wizard-shell-token" content="off">'))

    def test_update_lease_refused_by_the_boundary_is_no_lease(self):
        src = (MAC / 'Shared/UpdateContract.swift').read_text()
        m = block(src, 'static func maintenance(', 'static func releaseMaintenance(')
        self.assertIn('let noLeaseRoute = code == 404 || (code == 401 && body?["error"] as? String == "shell_token_required")', m)
        self.assertIn('if !release, noLeaseRoute, let onMissing {', m)
        self.assertIn('|| (release && code == 401 && body?["error"] as? String == "shell_token_required")', m)

    def test_guest_update_says_this_mac_app_sends_the_token(self):
        caps = json.loads((ROOT / 'next/guest/overlay/opt/wizard/host-capabilities.json').read_text())
        self.assertIs(caps['shell_token'], True)
        payload = (ROOT / 'next/guest/build-code-payload.py').read_text()
        self.assertIn("'opt/wizard/host-capabilities.json',", block(payload, 'CODE = (', '\n)'))


if __name__ == '__main__':
    unittest.main()
