"""HTTP and real-subprocess contract tests; no Docker, VM or live Wizard.
Run: python3 -m unittest discover -s next/guest/tests -v
"""
import asyncio
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

SETUP = Path(__file__).resolve().parents[1] / "overlay/opt/wizard/setup"
spec = importlib.util.spec_from_file_location("backup_frontdoor", SETUP / "backup_frontdoor.py")
assert spec is not None and spec.loader is not None
door_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(door_module)
HEADERS = {door_module.HEADER: door_module.HEADER_VALUE}
SECRET = "test-only-not-a-real-recovery-secret"
FAKE = '''import json, os, pathlib, sys, time
args = sys.argv[1:]
secret = None
if '--key-file' in args:
    p = pathlib.Path(args[args.index('--key-file') + 1])
    assert (p.stat().st_mode & 0o777) == 0o600
    assert (p.parent.stat().st_mode & 0o777) == 0o700
    secret = p.read_text()
    print(secret, file=sys.stderr)  # must never reach server logs or job output
if secret == 'fail-secret':
    print(json.dumps({'ok': False, 'error': secret})); sys.exit(1)
if secret == 'slow-secret':
    time.sleep(60)
if args[:2] == ['key', 'new']:
    r = {'ok': True, 'recovery_key': 'shown-only-once-fixture', 'key_id': '1234'}
elif args[:2] == ['key', 'show-id']:
    r = {'ok': True, 'stored': True, 'key_id': '1234'}
elif args[0] == 'status':
    r = {'ok': True, 'last_restore': {'stamp': 'fixture', 'status': 'paused', 'activated': False}, 'private': 'not public'}
else:
    if args[0] == 'export':
        pathlib.Path(args[args.index('-o')+1]).write_bytes(b'encrypted-fixture' * 1000)
    r = {'ok': True, 'manifest': {'agents': [{'id':'agent-one'}, {'id':'agent-two'}], 'apps':[{'id':'app-one'}],
        'files': {'bytes': 1234, 'count': 3}, 'secret_config': secret},
        'plan': {'install':['app-one'], 'replace':[], 'leave':[], 'agents':['agent-one', 'agent-two'], 'warnings':[]},
        'entries':12, 'content_bytes':3456, 'stamp':'fixture', 'digest_match': True}
print(json.dumps(r))
'''


class BackupHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fake = self.root / "fake.py"
        self.fake.write_text(FAKE)
        self.door = door_module.BackupDoor(self.root / "private-staging", [sys.executable, str(self.fake)])
        self.app = web.Application(client_max_size=8 << 20)
        door_module.install(self.app, self.door)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def post(self, path, data=None):
        return await self.client.post("/api/backup/" + path, json=data or {}, headers=HEADERS)

    async def upload(self, content=b"encrypted fixture"):
        res = await self.client.post("/api/backup/upload", data=content, headers=HEADERS)
        self.assertEqual(res.status, 201, await res.text())
        return await res.json()

    async def finish(self, response):
        self.assertEqual(response.status, 202, await response.text())
        j = await response.json()
        for _ in range(150):
            res = await self.client.get("/api/backup/jobs/" + j["id"], headers=HEADERS)
            j = await res.json()
            if j["state"] != "running":
                return j
            await asyncio.sleep(.02)
        self.fail("Job did not finish")

    async def test_all_routes_refuse_web_and_missing_headers_before_engine(self):
        for method, path in [("GET", "capabilities"), ("GET", "status"), ("GET", "jobs/abc"),
                ("GET", "jobs/abc/download"), ("POST", "key/new"), ("POST", "upload"),
                ("POST", "export"), ("POST", "undo"), ("POST", "activate"),
                ("POST", "jobs/abc/verify"), ("POST", "jobs/abc/import"), ("DELETE", "jobs/abc")]:
            for headers in [{}, {**HEADERS, "Origin": "null"}, {**HEADERS, "Origin": str(self.client.make_url('/')).rstrip('/')},
                            {**HEADERS, "Origin": ""}, {**HEADERS, "Origin": "https://evil.invalid"},
                            {**HEADERS, "Sec-Fetch-Site": "cross-site"}]:
                with self.subTest(method=method, path=path, headers=headers):
                    res = await self.client.request(method, "/api/backup/" + path, headers=headers)
                    self.assertEqual(res.status, 403)
                    self.assertNotIn("Access-Control-Allow-Origin", res.headers)
        self.assertEqual(self.door.jobs, {})
        self.assertFalse(self.door.root.exists())

    async def test_preflight_cannot_opt_into_native_transport(self):
        res = await self.client.options("/api/backup/export", headers={"Origin": "https://evil.invalid", "Access-Control-Request-Headers": door_module.HEADER})
        self.assertEqual(res.status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", res.headers)

    async def test_capability_and_missing_engine(self):
        res = await self.client.get("/api/backup/capabilities", headers=HEADERS)
        self.assertEqual((await res.json())["version"], 1)
        self.assertEqual(res.headers["Cache-Control"], "no-store")
        self.door.command = [str(self.root / "missing")]
        res = await self.client.get("/api/backup/capabilities", headers=HEADERS)
        self.assertEqual(res.status, 503)
        self.assertEqual((await res.json())["version"], 0)

    async def test_key_once_response_not_jobs_or_logs(self):
        logs = io.StringIO(); handler = logging.StreamHandler(logs); logging.getLogger().addHandler(handler)
        try:
            res = await self.post("key/new")
            self.assertEqual(res.status, 200)
            key = (await res.json())["recovery_key"]
            self.assertEqual(key, "shown-only-once-fixture")
            status = await self.client.get("/api/backup/status", headers=HEADERS)
            self.assertNotIn(key, await status.text())
            self.assertNotIn(key, logs.getvalue())
            self.assertEqual(self.door.jobs, {})
        finally:
            logging.getLogger().removeHandler(handler)

    async def test_stream_over_json_limit_private_mode_hash_and_discard(self):
        data = b"a" * (9 << 20)
        j = await self.upload(data)
        p = self.door.root / j["id"] / "bundle.wizardbackup"
        self.assertEqual(p.read_bytes(), data)
        self.assertEqual(j["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(p.parent.stat().st_mode), 0o700)
        self.assertNotIn("media", str(p))
        res = await self.client.delete("/api/backup/jobs/" + j["id"], headers=HEADERS)
        self.assertEqual(res.status, 200)
        self.assertFalse(p.exists())

    async def test_verify_then_confirm_import_removes_bundle_and_key(self):
        j = await self.upload()
        path = "jobs/" + j["id"]
        res = await self.post(path + "/import", {"secret": SECRET, "confirm": True})
        self.assertEqual(res.status, 409)
        verified = await self.finish(await self.post(path + "/verify", {"secret": SECRET}))
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(verified["result"]["agents"], ["agent-one", "agent-two"])
        for invalid in (None, False, 1, "true"):
            res = await self.post(path + "/import", {"secret": SECRET, "confirm": invalid})
            self.assertEqual(res.status, 400)
        done = await self.finish(await self.post(path + "/import", {"secret": SECRET, "confirm": True}))
        self.assertEqual(done["state"], "complete")
        folder = self.door.root / j["id"]
        self.assertFalse((folder / "bundle.wizardbackup").exists())
        self.assertEqual([p.name for p in folder.iterdir()], ["receipt.json"])
        self.assertNotIn(SECRET, (folder / "receipt.json").read_text())

    async def test_failure_key_not_in_logs_status_receipt_or_argv(self):
        logs = io.StringIO(); handler = logging.StreamHandler(logs); logging.getLogger().addHandler(handler)
        try:
            j = await self.upload()
            res = await self.finish(await self.post("jobs/" + j["id"] + "/verify", {"secret": "fail-secret"}))
            self.assertEqual(res["state"], "failed")
            self.assertNotIn("fail-secret", json.dumps(res))
            self.assertNotIn("fail-secret", logs.getvalue())
            folder = self.door.root / j["id"]
            self.assertFalse(list(folder.glob("key-*")))
            self.assertNotIn("fail-secret", (folder / "receipt.json").read_text())
        finally:
            logging.getLogger().removeHandler(handler)

    async def test_export_download_stream_deletes_guest_copy_no_head(self):
        done = await self.finish(await self.post("export", {"secret": SECRET}))
        self.assertEqual(done["state"], "complete")
        route = "jobs/" + done["id"] + "/download"
        self.assertEqual((await self.client.head("/api/backup/" + route, headers=HEADERS)).status, 405)
        res = await self.client.get("/api/backup/" + route, headers=HEADERS)
        content = await res.read()
        self.assertEqual(hashlib.sha256(content).hexdigest(), done["sha256"])
        self.assertEqual(len(content), done["total_bytes"])
        await asyncio.sleep(.01)
        self.assertFalse((self.door.root / done["id"] / "bundle.wizardbackup").exists())
        self.assertEqual((await self.client.get("/api/backup/" + route, headers=HEADERS)).status, 409)

    async def test_activation_and_undo_require_literal_owner_confirmation(self):
        for field, op in [("old_is_off", "activate"), ("confirm", "undo")]:
            for value in (None, False, 1, "true"):
                self.assertEqual((await self.post(op, {field: value})).status, 400)
            done = await self.finish(await self.post(op, {field: True}))
            self.assertEqual(done["state"], "complete")

    async def test_busy_and_cancel_cleanup(self):
        started = await self.post("export", {"secret": "slow-secret"})
        self.assertEqual(started.status, 202)
        ident = (await started.json())["id"]
        for _ in range(100):
            if self.door.processes:
                break
            await asyncio.sleep(.01)
        for proc in self.door.processes:
            # args inspected by subprocess factory in the dedicated test below, not /proc secrets.
            self.assertIsNone(proc.returncode)
        self.assertEqual((await self.post("undo", {"confirm": True})).status, 409)
        self.assertEqual((await self.post("key/new")).status, 409)
        self.assertEqual((await self.client.delete("/api/backup/jobs/" + ident, headers=HEADERS)).status, 409)
        for task in list(self.door.tasks):
            task.cancel()
        await asyncio.gather(*self.door.tasks, return_exceptions=True)
        self.assertFalse(self.door.lock.locked())
        self.assertFalse(list(self.door.root.rglob("key-*")))
        self.assertFalse(self.door.processes)

    async def test_secret_only_in_private_file_not_process_argv_or_env(self):
        real = asyncio.create_subprocess_exec
        seen = []
        async def launch(*args, **kw):
            seen.append((args, kw.get("env")))
            return await real(*args, **kw)
        with patch.object(door_module.asyncio, "create_subprocess_exec", side_effect=launch):
            await self.finish(await self.post("export", {"secret": SECRET}))
        self.assertEqual(len(seen), 1)
        self.assertNotIn(SECRET, repr(seen))
        self.assertIn("--key-file", seen[0][0])

    async def test_body_queries_bad_size_and_encoding_rejected(self):
        self.assertEqual((await self.post("export?secret=do-not-log", {"secret": SECRET})).status, 403)
        self.assertEqual((await self.client.post("/api/backup/export", data='["wrong"]', headers=HEADERS)).status, 400)
        self.assertEqual((await self.post("export", {"secret": 1})).status, 400)
        self.assertEqual((await self.post("export", {"secret": "x\ny"})).status, 400)
        self.assertEqual((await self.client.post("/api/backup/upload", data=b"", headers=HEADERS)).status, 413)
        with patch.object(door_module, "MAX_BYTES", 3):
            self.assertEqual((await self.client.post("/api/backup/upload", data=b"1234", headers=HEADERS)).status, 413)

    async def test_status_projects_no_private_fields(self):
        res = await self.client.get("/api/backup/status", headers=HEADERS)
        value = await res.json()
        self.assertEqual(value["last_restore"]["status"], "paused")
        self.assertNotIn("private", value)

    async def test_restart_drops_incoming_bundle_and_key_keeps_interrupted_note(self):
        j = await self.upload()
        folder = self.door.root / j["id"]
        door_module.private_write(folder / "key-orphan", SECRET)
        other = door_module.BackupDoor(self.door.root, self.door.command)
        await other.startup(None)
        try:
            self.assertFalse(folder.exists())
            self.assertEqual(other.jobs[j["id"]]["state"], "interrupted")
            self.assertNotIn(SECRET, json.dumps(other.jobs))
        finally:
            await other.cleanup(None)


if __name__ == "__main__":
    unittest.main()
