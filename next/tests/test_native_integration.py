"""Source-composition and isolated migration contracts (not guest/physical acceptance).
Run: python3 -m unittest discover -s next/tests -p 'test_native_integration.py' -v
"""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'guest/overlay/opt/wizard/bin/wizard-agent-ssh-migrate'
loader = importlib.machinery.SourceFileLoader('native_key_migrate', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
migrate = importlib.util.module_from_spec(spec)
loader.exec_module(migrate)


class TerminalMigration(unittest.TestCase):
    def managed(self):
        return dict(backend='ssh', ssh_host='wizard-vm', ssh_user='wizard', ssh_port=22, ssh_key=migrate.OLD)

    def test_old_and_new_managed_keys(self):
        for key in (migrate.OLD, migrate.NEW):
            self.assertTrue(migrate.uses_managed_terminal(dict(self.managed(), ssh_key=key)))

    def test_explicit_terminal_settings_are_not_migrated(self):
        for field, value in [('backend', 'local'), ('ssh_host', 'custom.invalid'), ('ssh_user', 'other'),
                             ('ssh_port', 2222), ('ssh_key', '/custom/key')]:
            with self.subTest(field=field):
                self.assertFalse(migrate.uses_managed_terminal(dict(self.managed(), **{field: value})))
        self.assertFalse(migrate.uses_managed_terminal({}))

    def test_explicit_route_exits_before_any_mutation(self):
        with patch.object(migrate, 'engine', return_value='fixture'), \
             patch.object(migrate, 'configured_terminal', return_value=dict(self.managed(), ssh_key='/custom/key')), \
             patch.object(migrate, 'sh') as sh, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(migrate.main(), 0)
            sh.assert_not_called()
            self.assertIn('explicit_or_unmanaged_terminal_preserved', output.getvalue())

    def test_ambiguous_engine_fails_closed(self):
        with patch.object(migrate, 'sh', return_value=Mock(stdout='one\ntwo\n')):
            with self.assertRaises(RuntimeError): migrate.engine()

    def test_unreadable_config_fails_closed(self):
        with patch.object(migrate, 'sh', return_value=Mock(returncode=1)):
            with self.assertRaises(RuntimeError): migrate.configured_terminal('fixture')


class Composition(unittest.TestCase):
    def test_build_preserves_updater_brand_and_import_inputs(self):
        build = (ROOT / 'mac/build.sh').read_text()
        for token in ('Shared/Brand.swift', 'Shared/UpdateContract.swift', 'Shared/GuestPatchCommand.swift',
                      'App/WizardUpdater.swift', 'App/WizardGuestActivation.swift', '-framework Sparkle',
                      'bring-hermes/wizard-bring-hermes', 'GUEST_UPDATE_PAYLOAD', 'SURequireSignedFeed=True',
                      'BUILD=${BUILD:?'):
            self.assertIn(token, build)
        self.assertNotIn('BUILD=${BUILD:-2}', build)
        self.assertIn('https://downloads.aiwizards.com/mac/appcast.xml', build)

    def test_native_slots_use_guest_home_first_contract(self):
        source = (ROOT / 'mac/App/main.swift').read_text()
        self.assertIn('slot == 1 ? "Home" : "App Workspace \\(slot - 1)"', source)
        self.assertIn('for slot in 1...9', source)
        self.assertIn('for slot in 2...9 { // Home is not a move destination.', source)
        self.assertIn('guard (1...9).contains(sender.tag)', source)
        self.assertIn('guard (2...9).contains(sender.tag)', source)
        self.assertIn('"Digit\\(sender.tag)", option: true', source)
        self.assertIn('"Digit\\(sender.tag)", shift: true, option: true', source)
        self.assertIn('"metaKey": !option, "altKey": option', source)
        self.assertIn('controller.overlay.isHidden, controller.window?.attachedSheet == nil', source)

    def test_onboarding_brand_assets_migrate_to_existing_guest(self):
        source = (ROOT / 'guest/upgrade-mvp-stack.py').read_text()
        for name in ('index.html', 'wizard-icon-32.png', 'wizard-mark-white.png'):
            self.assertIn('setup/static/' + name, source)
            self.assertTrue((ROOT / 'guest/overlay/opt/wizard/setup/static' / name).is_file())

    def test_fallback_uses_index_not_unrouted_root(self):
        source = (ROOT / 'mac/App/main.swift').read_text()
        self.assertIn('static let downloadsBase = "https://downloads.aiwizards.com/"', source)
        self.assertIn('URL(string: downloadsBase + "index.html")!', source)
        self.assertIn('Store.downloadsPage', source)

    def test_disk_uses_cached_full_sync(self):
        self.assertIn('cachingMode: .cached, synchronizationMode: .full', (ROOT / 'mac/Host/main.swift').read_text())


if __name__ == '__main__':
    unittest.main()
