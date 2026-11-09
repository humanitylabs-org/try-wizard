"""After Bring My Hermes, the importer reports whether a Claude or ChatGPT connection exists (try-wizard#51).

James (31 Oct): the AI runs only through Wizard's own connection apps, and the owner is asked to connect one when
none is connected. The Mac reads `ai_connected` from the import result: false asks, true or null (couldn't tell, or
an older guest) shows nothing new. Exercises the production helper with synthetic fixtures, without Hermes or a
network. Set IMPORTER_SCRIPT to run the same checks against another revision.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(os.environ.get(
    "IMPORTER_SCRIPT",
    str(Path(__file__).parents[1] / "overlay/opt/wizard/bin/wizard-import-hermes"),
))
loader = importlib.machinery.SourceFileLoader("importer_ai", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


def app(app_id, provides, port, status="running"):
    return {"id": app_id, "name": app_id, "status": status, "provides": ["ai-connection", provides],
            "view": {"local": f"http://127.0.0.1:{port}/"}}


CLAUDE = app("wizard-claude", "claude-subscription", 8811)
CHATGPT = app("wizard-chatgpt", "chatgpt-subscription", 8801)


def answer(by_url):
    seen = []

    def fetch(url):
        seen.append(url)
        status = by_url.get(url)
        if status is None:
            return None
        return {"contract": "wizard.ai-connection/1", "provider": "x", "status": status}
    return fetch, seen


class AiConnections(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.dir.cleanup)
        self.registry = Path(self.dir.name) / "apps.json"

    def check(self, apps, by_url, auth=None):
        if apps is not None:
            self.registry.write_text(json.dumps({"apps": apps}))
        fetch, seen = answer(by_url)
        return m.ai_connections(auth, fetch=fetch, registry_path=self.registry), seen

    def test_neither_connected_asks(self):
        res, seen = self.check([CLAUDE, CHATGPT], {"http://127.0.0.1:8811/api/connection": "not_connected",
                                                   "http://127.0.0.1:8801/api/connection": "expired"})
        self.assertIs(res["ai_connected"], False)
        self.assertEqual(res["ai_connections"], {"claude": "not_connected", "chatgpt": "expired"})
        self.assertEqual(sorted(seen), ["http://127.0.0.1:8801/api/connection", "http://127.0.0.1:8811/api/connection"])

    def test_no_connection_app_installed_asks(self):
        notes = {"id": "notes", "status": "running", "provides": ["notes"], "view": {"local": "http://127.0.0.1:9/"}}
        res, seen = self.check([notes], {})
        self.assertIs(res["ai_connected"], False)
        self.assertEqual(seen, [])

    def test_one_connected_shows_nothing_new(self):
        res, _ = self.check([CLAUDE, CHATGPT], {"http://127.0.0.1:8811/api/connection": "connected",
                                                "http://127.0.0.1:8801/api/connection": "not_connected"})
        self.assertIs(res["ai_connected"], True)

    def test_wizard_chatgpt_sign_in_in_auth_json_counts(self):
        auth = json.dumps({"providers": {"openai-codex": {"tokens": {"access_token": "fixture"}}}}).encode()
        res, seen = self.check([CHATGPT], {}, auth=auth)
        self.assertIs(res["ai_connected"], True)
        self.assertEqual(seen, [], "a provider already known connected is not asked again")
        self.assertNotIn("fixture", json.dumps(res), "the result never carries a token")

    def test_unreachable_app_or_missing_registry_is_unknown_not_a_prompt(self):
        res, _ = self.check([CLAUDE], {})
        self.assertIsNone(res["ai_connected"])
        self.assertEqual(res["ai_connections"], {"claude": "unknown"})
        self.registry.unlink()
        res, _ = self.check(None, {})
        self.assertIsNone(res["ai_connected"])

    def test_only_running_opted_in_apps_on_loopback_are_asked(self):
        stopped = app("wizard-claude", "claude-subscription", 8811, status="stopped")
        remote = dict(CHATGPT, view={"local": "http://169.254.169.254/"})
        res, seen = self.check([stopped, remote], {})
        self.assertEqual(seen, [])
        self.assertEqual(res["ai_connections"], {"chatgpt": "unknown"})
        self.assertIsNone(res["ai_connected"])

    def test_other_providers_do_not_count(self):
        tinfoil = app("wizard-tinfoil", "tinfoil-api-key", 8820)
        res, seen = self.check([tinfoil], {"http://127.0.0.1:8820/api/connection": "connected"})
        self.assertEqual(seen, [])
        self.assertIs(res["ai_connected"], False)

    def test_reply_without_the_contract_is_unknown(self):
        def fetch(url):
            return {"status": "connected"}
        self.registry.write_text(json.dumps({"apps": [CLAUDE]}))
        res = m.ai_connections(None, fetch=fetch, registry_path=self.registry)
        self.assertIsNone(res["ai_connected"])

    def test_import_result_carries_the_fields(self):
        src = SCRIPT.read_text()
        body = src[src.index("def _import_into"):src.index("def undo()")]
        self.assertIn("rec.update(ai_connections(wizard_auth))", body)
        self.assertIn('"ai_connected": rec.get("ai_connected")', body)
        self.assertLess(body.index("import readiness failed"), body.index("ai_connections(wizard_auth)"),
                        "the check runs after readiness and can't fail the import")


if __name__ == "__main__":
    unittest.main()
