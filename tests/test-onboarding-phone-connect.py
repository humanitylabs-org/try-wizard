#!/usr/bin/env python3
"""Mac onboarding's phone step is the shared phone-connect component, not its own copy of the UI.

The component lives in wizard-ux (web/core/phone-connect.js + .css), where Settings › Phones & devices and the Setup
app load it. Onboarding runs in the guest's own setup page, outside wizard-ux, so it carries a vendored copy synced
by next/guest/tools/sync-phone-connect.sh. These checks keep that copy unedited and actually in use."""

from pathlib import Path
import hashlib
import json
import re
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
STATIC = REPOSITORY / "next/guest/overlay/opt/wizard/setup/static"
VENDOR = STATIC / "vendor"


class OnboardingPhoneConnectTests(unittest.TestCase):
    def test_vendored_component_matches_its_provenance(self) -> None:
        provenance = json.loads((VENDOR / "phone-connect.provenance.json").read_text())
        self.assertEqual(provenance["source"], "humanitylabs-org/wizard-ux")
        self.assertRegex(provenance["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(set(provenance["sha256"]), {"phone-connect.js", "phone-connect.css", "../kit/controls.css"})
        for name, digest in provenance["sha256"].items():
            actual = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
            self.assertEqual(actual, digest, f"{name} was edited here; change wizard-ux and re-run sync-phone-connect.sh")

    def test_onboarding_loads_the_component_and_keeps_no_phone_ui_of_its_own(self) -> None:
        page = (STATIC / "index.html").read_text()
        self.assertIn('<script src="/static/vendor/qrcode.js"></script>', page)
        self.assertIn('<script src="/static/vendor/phone-connect.js"></script>', page)
        self.assertIn('<link rel="stylesheet" href="/static/vendor/phone-connect.css">', page)
        self.assertLess(page.index("vendor/qrcode.js"), page.index("vendor/phone-connect.js"))
        self.assertIn("WizPhoneConnect.create(", page)
        # Wording and states belong to the component, so every place says the same thing.
        for copy in ("Starting Tailscale", "approve the new device", "Waiting for your phone", "isn't available on this Wizard",
                     "Scan QR code", "createDataURL"):
            self.assertNotIn(copy, page.replace("\\'", "'"), f"onboarding renders {copy!r} itself")

    def test_device_copy_and_shared_kit(self) -> None:
        page = (STATIC / "index.html").read_text()
        component = (VENDOR / "phone-connect.js").read_text()
        self.assertIn("on another device</h1>", page)
        self.assertNotIn("on your phone</h1>", page)
        self.assertIn("Connect another device", component)
        self.assertNotIn("Link another device", component)
        self.assertIn('../kit/controls.css', (VENDOR / "phone-connect.css").read_text())
        self.assertTrue((STATIC / "kit/controls.css").is_file())

    def test_upgrade_installs_the_vendor_folder(self) -> None:
        upgrade = (REPOSITORY / "next/guest/upgrade-mvp-stack.py").read_text()
        self.assertTrue(re.search(r"'setup/static/vendor'", upgrade), "upgrades must install setup/static/vendor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
