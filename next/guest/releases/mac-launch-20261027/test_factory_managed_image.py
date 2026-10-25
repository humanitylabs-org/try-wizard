"""Store switching must not resurrect the hidden factory's managed image ID."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import factory_migrations as migrations

HERE = Path(__file__).resolve().parent
OLD = 'sha256:6c77d3d763f44b8b3f2fb219d90c5875c841c7c3c0fb3098a65c58e8aece36b7'
STOCK = 'f97608f178d1ffeca59860195ab7da295f7c8e5f'
PIN = 'ghcr.io/example/security-stock@sha256:' + 'b' * 64
NEW = 'sha256:' + 'c' * 64


def inherited():
    return [{'Image': OLD, 'Config': {'Labels': {'com.docker.compose.service': 'hermes-agent-engine'}},
             'FactoryImage': {'Config': {'Labels': {'ai.wizards.managed-launch': '1',
                                                    'ai.wizards.stock-revision': STOCK}}}}]


class RetainedManagedImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.manifest = self.work / 'managed-runtime.json'
        self.original = json.dumps({'image': OLD, 'stock': STOCK}, indent=2) + '\n'
        self.manifest.write_text(self.original)

    def retire(self, rows=None, active=()):
        return migrations.retire_hidden_managed_runtime(
            self.work, inherited() if rows is None else rows, active, self.manifest)

    def test_hidden_selection_archived_then_retired(self):
        self.assertEqual(self.retire()['image'], OLD)
        self.assertFalse(self.manifest.exists())
        archive = self.work / 'retired-managed-runtime.json'
        self.assertEqual(archive.read_text(), self.original)
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(self.retire())

    def test_active_image_cannot_be_retired(self):
        with self.assertRaisesRegex(AssertionError, 'still active'):
            self.retire(active=[OLD])
        self.assertEqual(self.manifest.read_text(), self.original)

    def test_unknown_or_ambiguous_selection_is_retained(self):
        for rows in [[], inherited() * 2, [{**inherited()[0], 'Image': NEW}]]:
            with self.subTest(rows=rows), self.assertRaises(AssertionError):
                self.retire(rows)
            self.assertEqual(self.manifest.read_text(), self.original)

    def test_unmanaged_engine_is_retained(self):
        rows = inherited()
        rows[0]['FactoryImage']['Config']['Labels']['ai.wizards.managed-launch'] = '0'
        with self.assertRaisesRegex(AssertionError, 'unmanaged'):
            self.retire(rows)
        self.assertTrue(self.manifest.exists())

    def test_symlink_and_evidence_overwrite_refused(self):
        target = self.work / 'target.json'
        self.manifest.rename(target)
        self.manifest.symlink_to(target)
        with self.assertRaisesRegex(AssertionError, 'symlink'):
            self.retire()
        self.manifest.unlink()
        target.rename(self.manifest)
        (self.work / 'retired-managed-runtime.json').write_text('previous evidence')
        with self.assertRaisesRegex(AssertionError, 'already exists'):
            self.retire()
        self.assertEqual(self.manifest.read_text(), self.original)

    def test_retirement_precedes_installer_and_managed_rebuild_is_retained(self):
        source = (HERE / 'guest-apply.py').read_text()
        self.assertLess(source.index('pristine()\n'), source.index('inherited=store.enable'))
        self.assertLess(source.index('migration.retire_hidden_managed_runtime('), source.index("'--prepare'"))
        self.assertLess(source.index('migration.retire_hidden_managed_runtime('), source.index("'bash',installer]"))
        self.assertLess(source.index("'bash',installer]"), source.index("'docker','build'"))
        self.assertLess(source.index("'docker','build'"), source.index("Path('/opt/wizard/managed-runtime.json').write_text"))
        self.assertIn("run(['sudo','-iu','wizard','wam','fresh-agent','connect'])", source)

    @unittest.skipUnless(os.environ.get('WAM_SOURCE'), 'set WAM_SOURCE to exact selected WAM checkout')
    def test_actual_wam_writer_cannot_resurrect_hidden_image_after_retirement(self):
        sys.path.insert(0, os.environ['WAM_SOURCE'])
        self.addCleanup(lambda: sys.path.remove(os.environ['WAM_SOURCE']))
        from wam import fresh_agent, managed_runtime
        # Use the real manifest reader, with only root ownership synthesized for
        # the unprivileged fixture. No renderer/selection/lifecycle logic is faked.
        manifest = Mock(wraps=self.manifest)
        manifest.lstat.return_value = SimpleNamespace(st_uid=0, st_mode=0o100644)
        fresh_agent.save(self.work / 'os-home', {'mode': 'fresh'})
        rt = self.work / 'runtipi'
        overlay = rt / 'user-config/wizardapps/hermes-agent/docker-compose.yml'
        overlay.parent.mkdir(parents=True)
        security_spec = importlib.util.spec_from_file_location('security_merge', HERE / 'guest-security-apply.py')
        security = importlib.util.module_from_spec(security_spec)
        security_spec.loader.exec_module(security)
        with patch.object(managed_runtime, 'MANIFEST', manifest), patch.object(security.os, 'chown'):
            security.merge(overlay, {'hermes-agent-engine': PIN})
            # Reproduces the failure: WAM selects a non-recreatable old ID over
            # the admitted security digest, even though the latter exists.
            fresh_agent.write_agent_overlay(rt, 'wizardapps', self.work / 'os-home')
            self.assertIn(OLD, overlay.read_text())
            self.assertNotIn(PIN, overlay.read_text())
            # Same migration and complete actual writer order after the fix.
            self.retire()
            security.merge(overlay, {'hermes-agent-engine': PIN})
            fresh_agent.write_agent_overlay(rt, 'wizardapps', self.work / 'os-home')
            self.assertNotIn(OLD, overlay.read_text())
            self.assertIn(PIN, overlay.read_text())
            # The normal post-install guard publication still wins, deliberately.
            self.manifest.write_text(json.dumps({'image': NEW, 'stock': STOCK}))
            fresh_agent.write_agent_overlay(rt, 'wizardapps', self.work / 'os-home')
            self.assertIn(NEW, overlay.read_text())
            self.assertIn('/wizard-managed-state', overlay.read_text())


if __name__ == '__main__':
    unittest.main()
