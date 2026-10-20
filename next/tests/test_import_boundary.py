"""Import HTTP boundary fixtures; no backups, containers, or user state are touched."""
import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer

SETUP = Path(__file__).resolve().parents[1] / 'guest/overlay/opt/wizard/setup/server.py'
spec = importlib.util.spec_from_file_location('import_boundary_server', SETUP)
assert spec and spec.loader
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ImportBoundary(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.incoming = Path(self.tmp.name)
        self.dir_patch = patch.object(server, 'IMPORT_DIR', self.incoming)
        self.dir_patch.start()
        self.tool_patch = patch.object(server, '_run_importer', new_callable=AsyncMock)
        self.tool = self.tool_patch.start()
        self.tool.return_value = (0, {'ok': True})
        self.proc_patch = patch.object(server.subprocess, 'run')
        self.proc = self.proc_patch.start()
        setattr(server, '_import_lock', asyncio.Lock())
        self.client = TestClient(TestServer(server.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.proc_patch.stop(); self.tool_patch.stop(); self.dir_patch.stop()
        self.tmp.cleanup()

    async def test_browser_origin_is_denied_even_with_import_header(self):
        for origin in ('https://untrusted.invalid', str(self.client.make_url('/')).rstrip('/')):
            for route in ('/api/agent-import', '/api/agent-import/undo'):
                resp = await self.client.post(route, data=b'fixture', headers={'Origin': origin, 'X-Wizard-Import': 'hermes-backup'})
                self.assertEqual(resp.status, 403)
        self.tool.assert_not_called(); self.proc.assert_not_called()

    async def test_missing_native_header_is_denied(self):
        resp = await self.client.post('/api/agent-import', data=b'fixture')
        self.assertEqual(resp.status, 403)
        self.tool.assert_not_called(); self.proc.assert_not_called()

    async def test_empty_backup_is_denied(self):
        resp = await self.client.post('/api/agent-import', data=b'', headers={'X-Wizard-Import':'hermes-backup'})
        self.assertEqual(resp.status, 413)
        self.tool.assert_not_called()

    async def test_busy_import_is_denied(self):
        async with server._import_lock:
            resp = await self.client.post('/api/agent-import', data=b'fixture', headers={'X-Wizard-Import':'hermes-backup'})
            self.assertEqual(resp.status, 409)
        self.tool.assert_not_called()

    async def test_native_upload_is_private_and_removed_after_success(self):
        async def importer(*args):
            path = Path(args[1])
            self.assertEqual(args[0], 'file')
            self.assertEqual(path.read_bytes(), b'fixture')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return 0, {'ok': True}
        self.tool.side_effect = importer
        resp = await self.client.post('/api/agent-import', data=b'fixture', headers={'X-Wizard-Import':'hermes-backup'})
        self.assertEqual(resp.status, 200)
        self.assertEqual(list(self.incoming.iterdir()), [])

    async def test_failed_import_removes_incoming_backup(self):
        self.tool.return_value = (1, {'ok': False})
        resp = await self.client.post('/api/agent-import', data=b'fixture', headers={'X-Wizard-Import':'hermes-backup'})
        self.assertEqual(resp.status, 500)
        self.assertEqual(list(self.incoming.iterdir()), [])

    async def test_native_undo_calls_only_undo(self):
        resp = await self.client.post('/api/agent-import/undo', data=b'{}', headers={'X-Wizard-Import':'hermes-backup'})
        self.assertEqual(resp.status, 200)
        self.tool.assert_awaited_once_with('undo')
        self.proc.assert_not_called()


if __name__ == '__main__': unittest.main()
