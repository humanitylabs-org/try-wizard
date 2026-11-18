"""try-wizard#110: "Name your Wizard" Continue must never dead-end on a plain-text 500.

Runs the real setup server in process (aiohttp test client) against temporary folders; Hermes is a test double.
"""
import asyncio
import errno
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

SERVER = Path(__file__).resolve().parents[1] / "overlay/opt/wizard/setup/server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("wizard_setup_server_name_test", SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load_server()


class NameStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "state"
        self.root.mkdir()
        self.runtipi = base / "runtipi"
        self.shell_data = self.runtipi / "app-data/wizardapps/wizard-shell/data"
        self.shell_data.mkdir(parents=True)
        self.patches = [
            patch.object(server, "ROOT", self.root),
            patch.object(server, "STATE_PATH", self.root / "setup.json"),
            patch.object(server, "PORTRAIT_PATH", self.root / "portrait"),
            patch.object(server, "VOICE_PATH", self.root / "voice.json"),
            patch.object(server, "RUNTIPI", self.runtipi),
            patch.object(server, "brain_exec", return_value={}),
        ]
        for p in self.patches:
            p.start()
        self.locked = []

    def tearDown(self):
        for path in self.locked:
            os.chmod(path, stat.S_IRWXU)
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def lock(self, path: Path):
        os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)
        self.locked.append(path)
        if os.access(path, os.W_OK):
            self.skipTest("running as root: permissions are not enforced")

    def post(self, data, raw=False):
        async def run():
            async with TestClient(TestServer(server.build_app())) as client:
                kwargs = {"data": data} if raw else {"json": data}
                response = await client.post("/api/name", **kwargs)
                text = await response.text()
                return response.status, response.content_type, text
        return asyncio.run(run())

    def assert_json_error(self, result, status=None):
        code, content_type, text = result
        self.assertEqual(content_type, "application/json", text)
        if status is not None:
            self.assertEqual(code, status)
        reason = json.loads(text)["error"]
        self.assertTrue(reason)
        self.assertNotIn("Request failed", reason)
        self.assertNotIn("Traceback", reason)
        return reason

    def test_name_saved_and_shell_settings_written(self):
        code, _, text = self.post({"name": "  Merlin  "})
        self.assertEqual(code, 200, text)
        self.assertEqual(json.loads(text)["name"], "Merlin")
        settings = json.loads((self.shell_data / "wizard-os/settings.json").read_text())
        self.assertEqual(settings["agent"]["name"], "Merlin")

    def test_unwritable_shell_settings_still_saves_name_and_reapplies_at_finish(self):
        self.lock(self.shell_data)
        code, _, text = self.post({"name": "Merlin"})
        self.assertEqual(code, 200, text)
        state = json.loads((self.root / "setup.json").read_text())
        self.assertEqual(state["name"], "Merlin")
        self.assertTrue(state["shellSettingsPending"])
        # finish re-applies the settings once the folder is writable again
        os.chmod(self.shell_data, stat.S_IRWXU)

        async def fake_shell(method, path, body=None, **_):
            return 200, {}

        with patch.object(server, "shell", side_effect=fake_shell):
            async def finish():
                async with TestClient(TestServer(server.build_app())) as client:
                    response = await client.post("/api/finish")
                    return response.status, await response.text()
            status, text = asyncio.run(finish())
        self.assertEqual(status, 200, text)
        settings = json.loads((self.shell_data / "wizard-os/settings.json").read_text())
        self.assertEqual(settings["agent"]["name"], "Merlin")
        self.assertFalse(json.loads((self.root / "setup.json").read_text())["shellSettingsPending"])

    def test_unwritable_state_dir_gives_plain_json_reason(self):
        self.lock(self.root)
        reason = self.assert_json_error(self.post({"name": "Merlin"}), 500)
        self.assertIn("permission denied", reason)

    def test_full_disk_gives_plain_json_reason(self):
        with patch.object(server, "save_state", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            reason = self.assert_json_error(self.post({"name": "Merlin"}), 507)
        self.assertIn("disk is full", reason)

    def test_bad_json_body_gives_json_error(self):
        self.assert_json_error(self.post("{not json", raw=True), 400)
        self.assert_json_error(self.post(["Merlin"]), 400)

    def test_any_other_failure_is_json_not_plain_text(self):
        with patch.object(server, "public_state", side_effect=RuntimeError("boom")):
            reason = self.assert_json_error(self.post({"name": "Merlin"}), 500)
        self.assertNotIn("boom", reason)


if __name__ == "__main__":
    unittest.main()
