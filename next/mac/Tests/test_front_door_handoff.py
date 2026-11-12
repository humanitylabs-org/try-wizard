"""Static contract for the onboarding hand-off (wizard-agent-service issue 95).

On a fresh install the front door's "Start chatting" sent the window to Wizard with
location.replace. WebKit marks that load same-site, and the Agent Service in the 0.7.0
guest refuses it with {"error":"same_origin_required"}. The window now cancels that page
load and loads the same URL itself, like a reload does. The decision itself is covered by
Tests/Backup/FrontDoorHandoffTests.swift (swift test); this checks the wiring that the CI
does not compile (App/main.swift is built only by build.sh on a Mac).
"""
from pathlib import Path
import unittest

MAC = Path(__file__).resolve().parents[1]
MAIN = (MAC / "App/main.swift").read_text()
HELPER = (MAC / "Shared/FrontDoorHandoff.swift").read_text()


def section(text, start, end):
    assert start in text, f"missing {start!r}"
    rest = text.split(start, 1)[1]
    assert end in rest, f"missing {end!r}"
    return rest.split(end, 1)[0]


class FrontDoorHandoffContract(unittest.TestCase):
    def test_helper_is_built_into_the_app_and_the_test_package(self):
        app_line = [l for l in (MAC / "build.sh").read_text().splitlines() if l.startswith('"${SWIFTC[@]}"') and 'Contents/MacOS/Wizard"' in l]
        self.assertEqual(len(app_line), 1)
        self.assertIn("Shared/FrontDoorHandoff.swift", app_line[0])
        self.assertIn('"FrontDoorHandoff.swift"', (MAC / "Package.swift").read_text())

    def test_policy_cancels_the_page_hand_off_and_loads_it_natively(self):
        policy = section(MAIN, "decidePolicyFor action: WKNavigationAction", "// App-origin iframe navigation")
        self.assertIn("if nativeHandoff == url {", policy)
        self.assertIn("Store.active?.kind == .thisMac", policy)
        self.assertIn("FrontDoorHandoff.needsNativeLoad(from: webView.url, to: url, method: action.request.httpMethod", policy)
        self.assertIn("mainFrame: action.targetFrame?.isMainFrame == true", policy)
        self.assertIn("setup: WizardShared.localSetupURL", policy)
        cancel = policy.index("decisionHandler(.cancel)")
        self.assertLess(policy.index("nativeHandoff = url"), cancel)
        self.assertLess(cancel, policy.index("self?.load(url)"))

    def test_own_cancel_does_not_bounce_back_to_the_front_door(self):
        failed = section(MAIN, "private func loadFailed(_ error: Error) {", "localRetries += 1")
        guard = 'if nativeHandoff != nil, failure.domain == "WebKitErrorDomain", failure.code == 102 { return }'
        self.assertIn(guard, failed)
        self.assertLess(failed.index(guard), failed.index("nativeHandoff = nil"))
        finished = section(MAIN, "didFinish navigation: WKNavigation!) {", "publishTitleBarInset()")
        self.assertIn("nativeHandoff = nil", finished)

    def test_helper_only_matches_front_door_to_wizard_get(self):
        self.assertIn("guard mainFrame, let current else { return false }", HELPER)
        self.assertIn('(method ?? "GET").uppercased() == "GET"', HELPER)
        self.assertIn("sameOrigin(current, setup) && sameOrigin(target, ux)", HELPER)


if __name__ == "__main__":
    unittest.main()
