"""Lightweight setup boundary/race tests; no Docker, OAuth or systemd required.
Run: python3 -m unittest discover -s next/tests -p test_setup_preparation.py -v
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from typing import Any
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer

SETUP = Path(__file__).resolve().parents[1] / "guest/overlay/opt/wizard/setup"
spec = importlib.util.spec_from_file_location("wizard_setup_preparation", SETUP / "server.py")
assert spec is not None and spec.loader is not None
server: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
A, B = "a" * 32, "b" * 32


class VoiceFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "voice.json"
        self.patcher = patch.object(server, "VOICE_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_missing_is_not_ready(self):
        self.assertEqual(server.voice_status()["state"], "preparing")

    def test_bounded_malformed_and_special_files(self):
        for raw in ["{" , "[]", "x" * 65537, '{"state":null}', '{"state":[]}']:
            with self.subTest(raw=raw[:20]):
                self.path.write_text(raw)
                self.assertEqual(server.voice_status()["state"], "error")
        self.path.unlink()
        self.path.symlink_to("/dev/zero")
        self.assertEqual(server.voice_status()["state"], "error")
        self.path.unlink()
        os.mkfifo(self.path)
        self.assertEqual(server.voice_status()["state"], "error")

    def test_allowlist_and_bytes_not_readiness(self):
        self.path.write_text(json.dumps({"state": "preparing", "detail": "loading secret=token",
            "downloaded": 100, "total": 100, "token": "private", "engine": {"password": "private"}}))
        view = server.voice_status()
        self.assertEqual(view, {"state": "preparing", "stage": "Loading voice model", "downloaded": 100, "total": 100})
        self.assertNotIn("secret", json.dumps(view))
        self.path.write_text(json.dumps({"state": "ready", "downloaded": -1, "total": True}))
        self.assertEqual(server.voice_status(), {"state": "ready", "stage": "Local voice ready", "downloaded": 0, "total": 0})

    def test_stages_and_legacy_contract(self):
        for state, detail, expected in [
            ("preparing", "wheel installing", "Installing voice dependencies"),
            ("preparing", "model downloading", "Downloading voice model"),
            ("preparing", "starting engine", "Starting voice engine"),
            ("retrying", "https://private.invalid?token=secret", "Local voice will retry"),
            ("error", "token=secret", "Local voice needs attention"),
            ("downloading", "loading", "Loading voice model"),
        ]:
            self.path.write_text(json.dumps({"state": state, "detail": detail}))
            self.assertEqual(server.voice_status()["stage"], expected)


class SetupHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        server._codex.clear()
        server._codex.update(status="idle")
        server._codex_lifecycle = asyncio.Lock()
        server._voice_retry_lock = asyncio.Lock()
        server._voice_retry_at = -float("inf")
        self.client = TestClient(TestServer(server.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def post(self, action, attempt=A):
        return await self.client.post("/api/brain/chatgpt/" + action, json={"attempt": attempt})

    async def test_status_no_cors_and_no_store(self):
        with patch.object(server, "voice_status", return_value={"state": "preparing"}):
            response = await self.client.get("/api/voice/status")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    async def test_cross_origin_rejected_before_mutation(self):
        with patch.object(server.subprocess, "run") as run:
            for headers in [{"Origin": "https://evil.invalid"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}]:
                response = await self.client.post("/api/voice/retry", headers=headers)
                self.assertEqual(response.status, 403)
            for path in ["start", "cancel", "open"]:
                response = await self.client.post("/api/brain/chatgpt/" + path,
                    json={"attempt": A}, headers={"Origin": "https://evil.invalid"})
                self.assertEqual(response.status, 403)
            run.assert_not_called()

    async def test_retry_single_flight_no_status_write(self):
        entered, release = threading.Event(), threading.Event()
        def start(*args, **kwargs):
            entered.set()
            release.wait(2)
            return subprocess.CompletedProcess(args[0], 0)
        with patch.object(server.subprocess, "run", side_effect=start) as run, patch.object(server, "save_state") as save:
            first = asyncio.create_task(self.client.post("/api/voice/retry"))
            await asyncio.to_thread(entered.wait, 1)
            second = await self.client.post("/api/voice/retry")
            self.assertEqual(second.status, 202)
            self.assertTrue((await second.json())["alreadyRequested"])
            release.set()
            self.assertEqual((await first).status, 202)
            third = await self.client.post("/api/voice/retry")
            self.assertEqual(third.status, 202)
            run.assert_called_once_with(["sudo", "-n", "systemctl", "--no-block", "start", "wizard-voice"],
                                       capture_output=True, text=True, timeout=5)
            save.assert_not_called()

    async def test_retry_failure_not_ready_and_can_retry(self):
        origin = str(self.client.make_url("/")).rstrip("/")
        with patch.object(server.subprocess, "run", side_effect=subprocess.TimeoutExpired("systemctl", 5)):
            response = await self.client.post("/api/voice/retry", headers={"Origin": origin})
        self.assertEqual(response.status, 503)
        self.assertNotIn("ready", await response.text())
        self.assertEqual(server._voice_retry_at, -float("inf"))

    async def test_attempt_required_duplicate_start_and_stale_cancel_poll(self):
        with patch.object(server.threading, "Thread") as worker:
            self.assertEqual((await self.post("start", "bad-token")).status, 400)
            self.assertEqual((await self.post("start")).status, 200)
            self.assertEqual((await self.post("start")).status, 200)
            worker.assert_called_once()
            self.assertEqual((await self.post("start", B)).status, 409)
            self.assertEqual((await self.post("cancel", B)).status, 409)
            self.assertEqual((await self.client.get("/api/brain/chatgpt?attempt=" + B)).status, 409)
            self.assertEqual(server._codex["attempt"], A)
            self.assertEqual((await self.post("cancel")).status, 200)
            self.assertEqual((await self.post("start", B)).status, 200)
            self.assertEqual((await self.post("cancel", A)).status, 409)
            self.assertEqual(server._codex["attempt"], B)

    async def test_failed_remote_cancel_blocks_new_start_and_other_brain(self):
        server._codex.update(status="waiting", attempt=A, container="test-container")
        with patch.object(server, "docker", return_value=subprocess.CompletedProcess([], 1)):
            self.assertEqual((await self.post("cancel")).status, 503)
        self.assertEqual(server._codex["status"], "cancelling")
        self.assertEqual((await self.post("start", B)).status, 409)
        self.assertEqual((await self.client.post("/api/brain", json={"kind": "free"})).status, 409)

    async def test_restart_serializes_cancel_and_new_attempt(self):
        server._codex.update(status="signed-in", attempt=A)
        entered, release = asyncio.Event(), asyncio.Event()
        async def restart():
            entered.set()
            await release.wait()
        with patch.object(server, "restart_hermes", side_effect=restart):
            polling = asyncio.create_task(self.client.get("/api/brain/chatgpt?attempt=" + A))
            await entered.wait()
            cancelling = asyncio.create_task(self.post("cancel"))
            await asyncio.sleep(.01)
            self.assertFalse(cancelling.done())
            release.set()
            self.assertEqual((await polling).status, 200)
            self.assertEqual((await cancelling).status, 200)
        self.assertEqual(server._codex["status"], "idle")

    async def test_late_engine_lookup_cannot_register_old_process(self):
        entered, release = threading.Event(), threading.Event()
        def engine():
            entered.set()
            release.wait(2)
            return "test-container"
        server._codex.update(status="starting", attempt=A)
        with patch.object(server, "engine", side_effect=engine), patch.object(server.subprocess, "Popen") as popen:
            task = asyncio.create_task(asyncio.to_thread(server._codex_worker, A))
            await asyncio.to_thread(entered.wait, 1)
            self.assertEqual((await self.post("cancel")).status, 200)
            server._codex.update(status="starting", attempt=B)
            release.set()
            await task
            popen.assert_not_called()
        self.assertEqual(server._codex["attempt"], B)

    async def test_stale_worker_success_and_error_cannot_publish(self):
        for message in [{"status": "signed-in", "brain": {"kind": "chatgpt"}}, {"error": "old error"}]:
            server._codex.clear()
            server._codex.update(status="starting", attempt=A)
            def lines():
                server._codex.clear()
                server._codex.update(status="starting", attempt=B)
                yield json.dumps(message) + "\n"
            proc = Mock(stdout=Mock())
            proc.stdout = iter(lines())
            # A closeable iterator models pipe delivery after cancellation.
            class Pipe:
                def __iter__(self): return lines()
                def close(self): pass
            proc.stdout = Pipe()
            with patch.object(server, "engine", return_value="container"), \
                 patch.object(server.subprocess, "Popen", return_value=proc), patch.object(server, "save_state") as save:
                await asyncio.to_thread(server._codex_worker, A)
                save.assert_not_called()
            self.assertEqual(server._codex, {"status": "starting", "attempt": B})


class RemoteProcessFenceTests(unittest.TestCase):
    """Exercise the actual wrapper/canceller with inert scripts, never OAuth."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        prefix = self.tmp.name + "/wizard-codex-"
        self.run_script = server._CODEX_RUN.replace("/tmp/wizard-codex-", prefix)
        self.cancel_script = server._CODEX_CANCEL.replace("/tmp/wizard-codex-", prefix)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cancel_before_remote_launch_prevents_stock_script(self):
        subprocess.run([sys.executable, "-c", self.cancel_script, A], check=True, timeout=2)
        marker = Path(self.tmp.name) / "should-not-exist"
        result = subprocess.run([sys.executable, "-c", self.run_script, "codex", A,
            f"from pathlib import Path; Path({str(marker)!r}).touch()"], timeout=2)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(marker.exists())

    def test_cancel_running_remote_process_before_next_auth(self):
        proc = subprocess.Popen([sys.executable, "-c", self.run_script, "codex", A,
            "import time; print('waiting', flush=True); time.sleep(30)"], stdout=subprocess.PIPE, text=True)
        assert proc.stdout is not None
        try:
            self.assertEqual(proc.stdout.readline().strip(), "waiting")
            subprocess.run([sys.executable, "-c", self.cancel_script, A], check=True, timeout=3)
            self.assertLess(proc.wait(timeout=2), 0)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()
            proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
