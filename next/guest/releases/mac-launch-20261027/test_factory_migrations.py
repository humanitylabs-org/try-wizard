import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import factory_migrations as migrations

HERE=Path(__file__).resolve().parent


def module(name):
    spec=importlib.util.spec_from_file_location('test_migration_'+name,HERE/(name+'.py'))
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj


class FactoryMigrationTests(unittest.TestCase):
    def test_legacy_is_removed_only_through_confirmed_lifecycle(self):
        from unittest.mock import Mock
        manager=Mock();manager.wait_status.side_effect=['stopped','missing']
        installed=Mock(side_effect=[{'wizard-shell'},set()])
        migrations.retire_legacy(manager,installed)
        manager.stop.assert_called_once_with('wizard-shell:wizardapps')
        manager.uninstall.assert_called_once_with('wizard-shell:wizardapps')

    def test_lifecycle_failure_does_not_get_a_success_receipt(self):
        from unittest.mock import Mock
        manager=Mock();manager.wait_status.return_value='running'
        with self.assertRaises(AssertionError):
            migrations.retire_legacy(manager,lambda:{'wizard-shell'})
        manager.uninstall.assert_not_called()

    def test_stopped_default_is_fatal_not_a_factory_exception(self):
        from unittest.mock import Mock
        manager=Mock();manager.wait_status.return_value='stopped'
        release={'default_apps':{'transcription':{'app':'transcriber'}}}
        with self.assertRaisesRegex(AssertionError,'default not running: transcriber'):
            migrations.default_states(manager,release)

    def test_all_declared_default_apps_are_checked(self):
        from unittest.mock import Mock
        manager=Mock();manager.wait_status.return_value='running'
        release={'default_apps':{'a':{'app':'wizard-ux'},'b':{'app':'wizard-agent-service'},'c':None}}
        result=migrations.default_states(manager,release)
        self.assertEqual(result,{'wizard-ux':'running','wizard-agent-service':'running'})
        self.assertEqual(manager.wait_status.call_count,2)

    def test_unknown_overlay_refused_and_retained(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'docker-compose.yml';path.write_text('services: {}\n')
            with self.assertRaisesRegex(AssertionError,'unknown factory overlay'):
                migrations.remove_known_overlay(path,'0'*64)
            self.assertTrue(path.exists())
            self.assertTrue(migrations.remove_known_overlay(path,hashlib.sha256(path.read_bytes()).hexdigest()))
            self.assertFalse(path.exists())

    def test_symlink_overlay_refused(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'target';target.write_text('private owner config')
            link=Path(td)/'link';link.symlink_to(target)
            with self.assertRaisesRegex(AssertionError,'unsafe factory overlay'):
                migrations.remove_known_overlay(link,hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(target.read_text(),'private owner config')

    def test_legacy_owner_sessions_block_retirement(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with contextlib.closing(sqlite3.connect(root/'state.sqlite3')) as c:
                c.execute('create table sessions(id text)')
            migrations.empty_legacy_state(root)
            with contextlib.closing(sqlite3.connect(root/'state.sqlite3')) as c:
                c.execute("insert into sessions values('owner')");c.commit()
            with self.assertRaisesRegex(AssertionError,'owner state refused'):
                migrations.empty_legacy_state(root)

    def test_local_trust_is_refreshed_from_public_key_and_keeps_other_hosts(self):
        with tempfile.TemporaryDirectory() as td,patch.object(migrations.os,'chown'):
            root=Path(td);key=root/'host.pub';key.write_text('ssh-ed25519 recipient-key guest\n')
            ssh=root/'data/.ssh';ssh.mkdir(parents=True)
            (ssh/'known_hosts').write_text('other ssh-ed25519 owner-host\nwizard-vm ssh-ed25519 factory-key\n')
            path=migrations.trust_local_host(root/'data',key)
            self.assertEqual(path.read_text(),'other ssh-ed25519 owner-host\nwizard-vm ssh-ed25519 recipient-key\n')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            key.write_text('ssh-ed25519 replacement-key guest\n')
            migrations.trust_local_host(root/'data',key)
            self.assertNotIn('recipient-key',path.read_text())
            self.assertEqual(path.read_text().count('wizard-vm '),1)

    def test_invalid_host_key_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);key=root/'host.pub';key.write_text('ssh-rsa wrong key')
            with self.assertRaisesRegex(AssertionError,'ED25519'):
                migrations.trust_local_host(root/'data',key)
            self.assertFalse((root/'data/.ssh').exists())

    def test_security_overlay_retains_ownership_and_compose_tags(self):
        security=module('guest-security-apply')
        with tempfile.TemporaryDirectory() as td,patch.object(security.os,'chown'):
            path=Path(td)/'wizard-ux/docker-compose.yml';path.parent.mkdir()
            path.write_text('# Written by wam (fresh mode)\nservices:\n  wizard-ux:\n    ports: !reset []\n    environment:\n      WIZARD_SHELL_LISTEN: \"127.0.0.1:8801\"\n')
            pin='ghcr.io/example/ux@sha256:'+'a'*64
            security.merge(path,{'wizard-ux':pin})
            self.assertTrue(path.read_text().startswith('# Written by wam'))
            self.assertIn('!reset',path.read_text())
            self.assertIn('\"127.0.0.1:8801\"',path.read_text())
            self.assertIn(pin,path.read_text())

    def test_foreign_overlay_is_not_laundered_as_wam_owned(self):
        security=module('guest-security-apply')
        with tempfile.TemporaryDirectory() as td,patch.object(security.os,'chown'):
            path=Path(td)/'wizard-agent-service/docker-compose.yml';path.parent.mkdir()
            path.write_text('services: {}\n')
            with self.assertRaisesRegex(AssertionError,'foreign fresh overlay'):
                security.merge(path,{'wizard-agent-service':'ghcr.io/example/agent@sha256:'+'b'*64})
            self.assertEqual(path.read_text(),'services: {}\n')

    def test_factory_steps_remain_ordered_and_fatal(self):
        src=(HERE/'guest-apply.py').read_text()
        self.assertLess(src.index('migration.clean_overlays'),src.index("'--prepare'"))
        self.assertLess(src.index('migration.prepare('),src.index("'bash',installer]"))
        self.assertIn("WIZARD_STRICT='1'",src)
        self.assertIn("assert connection['ok'] is True",src)
        self.assertIn("assert store_data['state']=='ready'",src)
        self.assertIn("'wam','doctor'],stream=True",src)
        self.assertIn("'WIZARD_TAILSCALE_WAIT'",src.replace("WIZARD_TAILSCALE_WAIT=", "'WIZARD_TAILSCALE_WAIT'="))
        self.assertIn('source-bundles/recorder.bundle',src)
        self.assertIn('Before=docker.service',src)
        self.assertNotIn('StrictHostKeyChecking=no',src)


if __name__=='__main__':unittest.main()
