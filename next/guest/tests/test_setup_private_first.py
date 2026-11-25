"""try-wizard#134: a fresh Mac starts private first (wizard-os DECISIONS #115, spec/AGENTS.md section 10).

Since try-wizard#171 a fresh Mac opens the front door standard first (no `?private_first=1`); private first runs when
the box asks for it or an older Mac sends `?private_first=1`. The old `PrivateFirstSetup` and `StandardFirstSetup`
switches are gone. With it on, the
setup's brain step leads with Tinfoil, runs none of its own brains (no ChatGPT device flow, no API key into Hermes'
.env), switches the box's `wizard/private-first-setup` on in the owner's Look file and hands over to the Wizard UX
Welcome, where the wizard-tinfoil app signs in and the Agent Service makes the private agent the default. Claude and
ChatGPT are only offered as a separate second agent.

Runs the real setup server in process (aiohttp test client); the Agent Service is a fake behind `shell()`.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

SETUP = Path(__file__).resolve().parents[1] / "overlay/opt/wizard/setup"
REPO = Path(__file__).resolve().parents[3]


def load_server():
    spec = importlib.util.spec_from_file_location("wizard_setup_server_private_first_test", SETUP / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load_server()


class FakeAgentService:
    """GET /wizard/v1/private-first and the Pages file API for Pages/wizard-look/look.json."""

    def __init__(self, route=True, on=False, look=None, stale_reads=0):
        self.route, self.on, self.look, self.version = route, on, look, ("v1" if look is not None else None)
        self.calls = []
        self.conflicts = 0
        # Reads after a save that still answer the old value (the Agent Service's 3 s switch cache).
        self.stale_reads, self.stale_left, self.answered = stale_reads, 0, []

    async def __call__(self, method, path, body=None, *, timeout=60, headers=None):
        self.calls.append((method, path, body))
        if path == server.PRIVATE_FIRST_STATE:
            if not self.route:
                return 404, {"error": "not_found"}
            on = self.on
            if self.stale_left:
                self.stale_left -= 1
                on = not self.on
            self.answered.append(on)
            return 200, {"schema": "wizard.private-first/1", "on": on, "standard_agent": "hermes",
                         "private_agent": None, "standard_on": True}
        if path == server.LOOK_FILE and method == "GET":
            if self.look is None:
                return 404, {"error": "file_not_found", "exists": False}
            return 200, {"exists": True, "text": self.look, "version": self.version}
        if path == server.LOOK_FILE and method == "PUT":
            if self.conflicts:
                self.conflicts -= 1
                self.look, self.version = json.dumps({"version": 1, "skin": {"id": "nebula", "at": 7}, "tweaks": {}}), "v9"
                return 409, {"error": "stale_version"}
            if body.get("version") != self.version:
                return 409, {"error": "stale_version"}
            self.look, self.version = body["text"], "v2"
            # The Agent Service reads the switch from this file (channels-switch.mjs lookSwitchOn).
            look = json.loads(self.look)
            on = look.get("version") == 1 and look.get("tweaks", {}).get(server.PRIVATE_FIRST_SWITCH, {}).get("on") is True
            if on != self.on:
                self.stale_left = self.stale_reads
            self.on = on
            return 200, {"exists": True, "version": "v2"}
        return 404, {"error": "not_found"}


_real_sleep = asyncio.sleep


async def _no_sleep(_seconds):
    await _real_sleep(0)


class PrivateFirstSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "state"
        self.root.mkdir()
        self.runtipi = base / "runtipi"
        (self.runtipi / "app-data/wizardapps/wizard-shell/data").mkdir(parents=True)
        self.brains = []
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("WIZARD_PRIVATE_FIRST", None)
        self.patches = [
            patch.object(server, "ROOT", self.root),
            patch.object(server, "STATE_PATH", self.root / "setup.json"),
            patch.object(server, "PORTRAIT_PATH", self.root / "portrait"),
            patch.object(server, "VOICE_PATH", self.root / "voice.json"),
            patch.object(server, "RUNTIPI", self.runtipi),
            patch.object(server, "brain_exec", side_effect=lambda command, payload=None, timeout=120: self.brains.append(command) or {"kind": command}),
            patch.object(server, "restart_hermes", side_effect=self.no_restart),
        ]
        for p in self.patches:
            p.start()

    async def no_restart(self):
        return None

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def run_with(self, service, steps):
        async def run():
            with patch.object(server, "shell", service):
                async with TestClient(TestServer(server.build_app())) as client:
                    out = []
                    for method, path, body in steps:
                        response = await client.request(method, path, json=body)
                        out.append((response.status, await response.json()))
                    return out
        return asyncio.run(run())

    # ── off by default ──

    def test_off_by_default_the_old_brains_run(self):
        service = FakeAgentService()
        (state_status, state), (status, _) = self.run_with(service, [
            ("GET", "/api/state", None), ("POST", "/api/brain", {"kind": "free"})])
        self.assertEqual(state_status, 200)
        self.assertFalse(state["privateFirst"]["on"])
        self.assertEqual(status, 200)
        self.assertEqual(self.brains, ["free"])
        self.assertFalse(any(path == server.LOOK_FILE for _, path, _ in service.calls), "off never writes the Look file")

    def test_private_brain_refused_while_off(self):
        service = FakeAgentService()
        [(status, body)] = self.run_with(service, [("POST", "/api/brain/private", {})])
        self.assertEqual(status, 409)
        self.assertNotIn("done", json.loads((self.root / "setup.json").read_text()) if (self.root / "setup.json").exists() else {})

    def test_older_agent_service_keeps_the_old_brains_even_when_asked(self):
        service = FakeAgentService(route=False)
        (_, state), (status, _) = self.run_with(service, [
            ("POST", "/api/private-first", {"ask": True}), ("POST", "/api/brain", {"kind": "free"})])
        self.assertFalse(state["privateFirst"]["on"])
        self.assertFalse(state["privateFirst"]["supported"])
        self.assertEqual(status, 200)

    def test_env_zero_forces_off(self):
        os.environ["WIZARD_PRIVATE_FIRST"] = "0"
        service = FakeAgentService(on=True)
        [(_, state)] = self.run_with(service, [("POST", "/api/private-first", {"ask": True})])
        self.assertFalse(state["privateFirst"]["on"])
        self.assertNotIn("privateFirst", json.loads((self.root / "setup.json").read_text()) if (self.root / "setup.json").exists() else {})

    # ── on ──

    def test_mac_asks_then_tinfoil_leads_and_own_brains_are_refused(self):
        service = FakeAgentService()
        out = self.run_with(service, [
            ("POST", "/api/private-first", {"ask": True}),
            ("POST", "/api/brain", {"kind": "apikey", "provider": "anthropic", "key": "sk-ant-" + "x" * 30}),
            ("POST", "/api/brain", {"kind": "free"}),
            ("POST", "/api/brain/chatgpt/start", {"attempt": "a" * 32}),
        ])
        self.assertTrue(out[0][1]["privateFirst"]["on"])
        for status, body in out[1:]:
            self.assertEqual(status, 409, body)
            self.assertIn("Tinfoil", body["error"])
        self.assertEqual(self.brains, [], "no ChatGPT device flow and no API key written into Hermes")
        self.assertEqual(server._codex.get("status", "idle"), "idle")

    def test_box_switch_alone_turns_it_on(self):
        service = FakeAgentService(on=True)
        [(_, state)] = self.run_with(service, [("GET", "/api/state", None)])
        self.assertTrue(state["privateFirst"]["on"])

    def test_env_one_turns_it_on(self):
        os.environ["WIZARD_PRIVATE_FIRST"] = "1"
        [(_, state)] = self.run_with(FakeAgentService(), [("GET", "/api/state", None)])
        self.assertTrue(state["privateFirst"]["on"])

    def test_continue_switches_the_box_on_and_hands_over_to_the_welcome(self):
        service = FakeAgentService()
        (self.root / "setup.json").write_text(json.dumps({"name": "Merlin"}))
        out = self.run_with(service, [
            ("POST", "/api/private-first", {"ask": True}), ("POST", "/api/brain/private", {})])
        status, body = out[1]
        self.assertEqual(status, 200, body)
        # No ?session= deep link: the Welcome opens at Connect your AI (Tinfoil first) instead of being kept away.
        self.assertEqual(body["target"], f"{server.PUBLIC_UX_ORIGIN}{server.UX_PATH}")
        look = json.loads(service.look)
        self.assertEqual(look["version"], 1)
        self.assertIs(look["tweaks"]["wizard/private-first-setup"]["on"], True)
        self.assertGreater(look["tweaks"]["wizard/private-first-setup"]["at"], 0)
        self.assertTrue(service.on, "the Agent Service now reads private first on")
        saved = json.loads((self.root / "setup.json").read_text())
        self.assertTrue(saved["done"])
        self.assertEqual(saved["brain"]["provider"], "tinfoil")
        self.assertIsNone(saved["firstSessionId"])
        self.assertEqual(self.brains, [], "nothing attached to Hermes by the setup itself")
        # Private first never touches the main Hermes's model: no brain command and no Hermes restart ran.

    def test_hand_over_waits_until_the_agent_service_reads_it_on(self):
        # The Agent Service caches the switch for 3 s; the Welcome reads it once, so the hand-over waits for on:true.
        service = FakeAgentService(stale_reads=3)
        (self.root / "setup.json").write_text(json.dumps({"name": "Merlin"}))
        with patch.object(server.asyncio, "sleep", new=_no_sleep):
            out = self.run_with(service, [
                ("POST", "/api/private-first", {"ask": True}), ("POST", "/api/brain/private", {})])
        self.assertEqual(out[1][0], 200, out[1][1])
        self.assertEqual(service.answered[-4:], [False, False, False, True], "polled until the Agent Service said on")

    def test_hand_over_still_happens_if_the_agent_service_never_reads_it_on(self):
        service = FakeAgentService(stale_reads=10**6)
        (self.root / "setup.json").write_text(json.dumps({"name": "Merlin"}))
        with patch.object(server, "PRIVATE_FIRST_SETTLE_S", 0.0):
            out = self.run_with(service, [
                ("POST", "/api/private-first", {"ask": True}), ("POST", "/api/brain/private", {})])
        self.assertEqual(out[1][0], 200, out[1][1])
        self.assertTrue(json.loads((self.root / "setup.json").read_text())["done"])

    def test_existing_look_file_keeps_the_owners_choices(self):
        old = {"version": 1, "skin": {"id": "nebula", "at": 4},
               "tweaks": {"wizard/chat-channels": {"on": True, "at": 9}}, "views": {"desktop": {"id": "", "at": 2}}}
        service = FakeAgentService(look=json.dumps(old))
        out = self.run_with(service, [("POST", "/api/private-first", {"ask": True}), ("POST", "/api/brain/private", {})])
        self.assertEqual(out[1][0], 200, out[1][1])
        look = json.loads(service.look)
        self.assertEqual(look["skin"], old["skin"])
        self.assertEqual(look["views"], old["views"])
        self.assertEqual(look["tweaks"]["wizard/chat-channels"], {"on": True, "at": 9})
        self.assertEqual(look["tweaks"]["wizard/private-first-setup"], {"on": True, "at": 10})

    def test_stale_look_save_is_retried_on_the_newer_file(self):
        service = FakeAgentService(look=json.dumps({"version": 1, "skin": None, "tweaks": {}}))
        service.conflicts = 1
        out = self.run_with(service, [("POST", "/api/private-first", {"ask": True}), ("POST", "/api/brain/private", {})])
        self.assertEqual(out[1][0], 200, out[1][1])
        look = json.loads(service.look)
        self.assertEqual(look["skin"], {"id": "nebula", "at": 7})
        self.assertEqual(look["tweaks"]["wizard/private-first-setup"], {"on": True, "at": 8})

    def test_unreadable_look_file_is_never_overwritten(self):
        service = FakeAgentService(look="{not json")
        out = self.run_with(service, [("POST", "/api/private-first", {"ask": True}), ("POST", "/api/brain/private", {})])
        self.assertEqual(out[1][0], 502)
        self.assertEqual(service.look, "{not json")
        self.assertFalse(json.loads((self.root / "setup.json").read_text()).get("done"))

    def test_ask_after_setup_is_done_changes_nothing(self):
        (self.root / "setup.json").write_text(json.dumps({"name": "Merlin", "done": True}))
        [(_, state)] = self.run_with(FakeAgentService(), [("POST", "/api/private-first", {"ask": True})])
        self.assertFalse(state["privateFirst"]["on"], "an existing install is not moved")


class PageAndMacSwitch(unittest.TestCase):
    """The page leads with Tinfoil when on, and the Mac switch is off by default."""

    def setUp(self):
        self.html = (SETUP / "static/index.html").read_text()
        self.swift = (REPO / "next/mac/App/main.swift").read_text()

    def test_page_has_a_tinfoil_lead_and_second_agent_note(self):
        lead = re.search(r'<div class="choices hidden" id="pfChoices">(.*?)</div>\s*<p', self.html, re.S).group(1)
        self.assertIn('data-kind="private"', lead)
        self.assertIn("<b>Tinfoil</b>", lead)
        self.assertIn('<span class="tag">Recommended</span>', lead)
        self.assertNotIn("chatgpt", lead.lower())
        self.assertIn("Add one later as a second agent. Your private agent and its apps stay private.", self.html)
        self.assertIn("'/api/brain/private'", self.html)
        self.assertIn("private_first", self.html)

    def test_mac_opens_standard_first_for_everyone(self):
        block = self.swift[self.swift.index("enum WizardPrivateFirstSetup"):]
        block = block[:block.index("\n}\n") + 3]
        # try-wizard#171 switch-default: standard first for everyone, no switch, no ?private_first=1.
        self.assertIn('static var setupURL: URL { URL(string: "http://127.0.0.1:\\(WizardShared.setupPort)/")! }', block)
        self.assertNotIn("private_first=1", block)
        self.assertNotIn("UserDefaults", block)
        self.assertNotIn('bool(forKey: "StandardFirstSetup")', self.swift)
        self.assertNotIn("standardFirstKey", self.swift)
        self.assertNotIn('UserDefaults.standard.bool(forKey: "PrivateFirstSetup")', self.swift)
        # The stored values of both old switches are cleared at launch.
        self.assertIn('UserDefaults.standard.removeObject(forKey: "PrivateFirstSetup")', self.swift)
        self.assertIn('UserDefaults.standard.removeObject(forKey: "StandardFirstSetup")', self.swift)
        # Both places the window opens the front door on This Mac (ready, and the quiet retry).
        self.assertEqual(self.swift.count("load(WizardPrivateFirstSetup.setupURL)"), 2)
        self.assertNotIn("self.load(WizardShared.localSetupURL)", self.swift)
        self.assertNotIn("self?.load(WizardShared.localSetupURL)", self.swift)

    def test_page_asks_only_when_the_mac_sent_private_first(self):
        self.assertIn("get('private_first') === '1'", self.html)
        self.assertIn("if (pfAsked && !state.done) state = await api('/api/private-first'", self.html)


class StandardFirstMac(unittest.TestCase):
    """try-wizard#171: a Mac opens the front door without `?private_first=1`, so the page
    never asks; a fresh box (the Agent Service says off) takes Claude or ChatGPT as its first agent."""

    setUp, tearDown = PrivateFirstSetup.setUp, PrivateFirstSetup.tearDown
    no_restart, run_with = PrivateFirstSetup.no_restart, PrivateFirstSetup.run_with

    def test_fresh_box_takes_claude_and_chatgpt(self):
        started = []
        service = FakeAgentService()
        with patch.object(server, "_codex_worker", side_effect=lambda attempt: started.append(attempt)):
            out = self.run_with(service, [
                ("GET", "/api/state", None),
                ("POST", "/api/brain", {"kind": "apikey", "provider": "anthropic", "key": "sk-ant-" + "x" * 30}),
                ("POST", "/api/brain/chatgpt/start", {"attempt": "b" * 32}),
            ])
        self.assertFalse(out[0][1]["privateFirst"]["on"])
        self.assertEqual(out[1][0], 200, out[1][1])
        self.assertEqual(out[2][0], 200, out[2][1])
        for _, body in out:
            self.assertNotIn(server.PRIVATE_FIRST_REFUSAL, json.dumps(body))
        self.assertEqual(self.brains, ["apikey"])
        self.assertEqual(started, ["b" * 32])
        self.assertFalse(any(path == server.LOOK_FILE for _, path, _ in service.calls), "standard first never writes the Look file")
        with server._codex_lock:
            server._codex.clear()
            server._codex.update(status="idle")

    def test_private_first_still_runs_when_the_box_asks(self):
        os.environ["WIZARD_PRIVATE_FIRST"] = "1"
        [(status, body)] = self.run_with(FakeAgentService(), [("POST", "/api/brain", {"kind": "free"})])
        self.assertEqual((status, body["error"]), (409, server.PRIVATE_FIRST_REFUSAL))

    def test_a_setup_that_already_asked_is_not_moved(self):
        (self.root / "setup.json").write_text(json.dumps({"name": "Merlin", "privateFirst": True}))
        [(status, _)] = self.run_with(FakeAgentService(), [("POST", "/api/brain", {"kind": "free"})])
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()
