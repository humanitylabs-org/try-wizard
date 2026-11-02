#!/usr/bin/env python3
"""Light factory contracts, WAM trigger tests and a tiny offline ext4 regression.
No VM, Docker daemon, image build, publication or feed access.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import types
import sys
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load('factory-policy')
background = load('post-setup-apps')
compact = load('compact-ext4')
freeze = load('freeze-release')


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads((HERE / 'pins.json').read_text())
        self.full = json.loads((HERE / 'wizard-os-release-candidate.json').read_text())

    def test_only_onboarding_and_its_declared_dependencies_are_preloaded(self):
        small, full = policy.releases(self.full)
        self.assertEqual(set(small['default_apps']), set(self.pins['factory']['onboardingSlots']))
        apps = {r['app'] for r in small['default_apps'].values()}
        self.assertEqual(apps, {'wizard-ux', 'wizard-agent-service', 'hermes-agent', 'wizard-chatgpt',
                                'wizard-claude', 'transcriber', 'files'})
        self.assertTrue({'wizard-recorder', 'browser', 'secret-drop', 'notifications',
                         'wizard-voice-service', 'wizard-connection-router'}.isdisjoint(apps))
        self.assertEqual(set(full['default_apps']), set(self.full['default_apps']))
        self.assertEqual(full['default_apps']['recorder']['commit'], self.pins['finalPins']['recorder'])
        self.assertTrue(all(r['install'] == 'bootstrap' for r in full['default_apps'].values() if r))
        self.assertEqual(self.full['default_apps']['recorder']['install'], 'portable-app')

    def test_missing_onboarding_pin_is_not_silently_accepted(self):
        del self.full['default_apps']['transcription']
        with self.assertRaises(AssertionError):
            policy.releases(self.full)

    def test_current_stable_is_an_immutable_matching_snapshot(self):
        stable_bytes = (HERE / self.pins['stable']['manifest']).read_bytes()
        stable = json.loads(stable_bytes)
        self.assertEqual(stable['version'], '0.3.68')
        self.assertEqual(stable['version'], self.pins['stable']['version'])
        self.assertEqual(hashlib.sha256(stable_bytes).hexdigest(), self.pins['stable']['sha256'])
        self.assertEqual(stable['default_apps'], self.pins['stable']['default_apps'])
        self.assertEqual(self.full['baseRelease']['version'], stable['version'])
        self.assertEqual(self.full['baseRelease']['sha256'], self.pins['stable']['sha256'])
        source = self.pins['stable']['source']
        self.assertIn('/' + source['commit'] + '/', source['html_url'])
        self.assertEqual(len(source['commit']), 40)
        self.assertEqual(self.full, freeze.freeze(self.pins, stable, stable_bytes, source))

    def test_all_executable_recipe_inputs_are_pinned_together(self):
        self.assertEqual(self.pins['execution']['sha256'], hashlib.sha256((HERE / 'assemble.py').read_bytes()).hexdigest())
        for rel, digest in self.pins['execution']['inputs'].items():
            self.assertEqual(hashlib.sha256((HERE / rel.removeprefix('preparation/')).read_bytes()).hexdigest(), digest)
        self.assertTrue({'preparation/factory-policy.py', 'preparation/compact-ext4.py',
                         'preparation/factory-cleanup.py', 'preparation/post-setup-apps.py',
                         'preparation/guest-apply.py'}.issubset(self.pins['execution']['inputs']))

    def test_no_48_gib_factory_growth_and_install_bytes_are_packed_size(self):
        self.assertEqual(self.pins['factory']['diskGB'], 16)
        self.assertEqual(self.pins['factory']['userDiskGB'], 64)
        recipe = (HERE / 'assemble.py').read_text()
        self.assertNotIn('resize2fs /dev/vda', recipe)
        self.assertNotRegex(recipe, r'(truncate|resize2fs).*48\s*([*<]|GiB)')
        self.assertIn('compactor.compact(sealed', recipe)
        self.assertIn("'installBytes':sum((out/x).stat().st_size for x in files)", recipe)
        self.assertIn("'baseRelease':pins['stable']['version']", recipe)
        self.assertIn("'stack':'wizard-os-0.3.39-runtipi'", recipe)
        # Existing native installer uses stack equality to preserve the owner's disk.
        # Source provenance must change independently from this compatibility ID.
        native = (HERE.parents[2] / 'mac/App/main.swift').read_text()
        self.assertIn('truncate(atOffset: 64 << 30)', native)
        grow = (HERE / 'factory-units/wizard-grow.service').read_text()
        self.assertIn('ConditionKernelCommandLine=!wizard.factory=1', grow)
        self.assertIn('ExecStart=/sbin/resize2fs /dev/vda', grow)
        self.assertIn('rw wizard.factory=1', recipe)

    def test_voice_is_prepared_before_seal_and_unused_preloads_are_pruned(self):
        apply = (HERE / 'guest-apply.py').read_text()
        self.assertIn("'fetch-voice'],timeout=1800", apply)
        self.assertLess(apply.index("'fetch-voice'"), apply.index('cleanup.prune'))
        self.assertIn('trim(final=True)', apply)
        self.assertIn('install_package(ROOT/\'preparation/factory-units\'', apply)
        self.assertNotIn('wizard-default-apps', (HERE.parents[1] / 'overlay/opt/wizard/setup/server.py').read_text())


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'setup.json'
        self.release = self.root / 'release.json'
        self.home = self.root / 'home'
        self.release.write_text(json.dumps({'version': 'test', 'default_apps': {}}))
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0, 'warming up\n' + json.dumps({'failed': {}, 'installed': []}), ''))

    def run_trigger(self):
        return background.run(self.state, self.release, self.home, self.runner)

    def test_no_download_before_setup_completes(self):
        for raw in (None, '{}', '[]', 'null', '{"done": false}', '{"done": "true"}', 'bad'):
            if raw is not None:
                self.state.write_text(raw)
            self.assertFalse(self.run_trigger())
        self.runner.assert_not_called()
        self.assertFalse(self.home.exists())

    def test_wam_bootstrap_is_the_only_installer_and_is_idempotent(self):
        self.state.write_text('{"done": true}')
        with patch.dict(os.environ, {'WAM_REF': 'main', 'WIZARD_UX_IMAGE': 'unselected'}):
            self.assertTrue(self.run_trigger())
        args, kw = self.runner.call_args
        self.assertEqual(args[0], [str(background.WAM), 'bootstrap'])
        self.assertEqual(kw['env']['WIZARD_RELEASE_PINS'], str(self.release))
        self.assertNotIn('WAM_REF', kw['env'])
        self.assertNotIn('WIZARD_UX_IMAGE', kw['env'])
        self.assertEqual((self.home / 'release-pins.json').read_bytes(), self.release.read_bytes())
        self.assertTrue(self.run_trigger())
        self.assertEqual(self.runner.call_count, 1)

    def test_partial_failure_and_malformed_reply_retry_after_restart(self):
        self.state.write_text('{"done": true}')
        for stdout in ('{"failed":{"browser":"offline"}}', 'not json', '{"installed":[]}'):
            self.runner.return_value.stdout = stdout
            self.assertFalse(self.run_trigger())
            self.assertFalse((self.home / 'factory-default-apps.done').exists())
        self.runner.return_value.stdout = '{"failed":{}}'
        self.assertTrue(self.run_trigger())
        self.assertEqual(self.runner.call_count, 4)

    def test_download_process_failure_is_not_marked_done(self):
        self.state.write_text('{"done": true}')
        self.runner.side_effect = subprocess.CalledProcessError(1, 'wam')
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_trigger()
        self.assertFalse((self.home / 'factory-default-apps.done').exists())

    def test_missing_factory_manifest_does_not_opt_existing_installs_in(self):
        self.state.write_text('{"done": true}')
        self.release.unlink()
        self.assertFalse(self.run_trigger())
        self.runner.assert_not_called()

    def test_competing_timer_or_agent_process_does_not_install_twice(self):
        import fcntl
        self.state.write_text('{"done": true}')
        self.home.mkdir()
        with (self.home / 'factory-default-apps.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertFalse(self.run_trigger())
        self.runner.assert_not_called()

    def test_timer_retries_offline_without_a_setup_wait_screen(self):
        timer = (HERE / 'factory-units/wizard-default-apps.timer').read_text()
        service = (HERE / 'factory-units/wizard-default-apps.service').read_text()
        self.assertIn('OnUnitInactiveSec=60s', timer)
        self.assertIn('User=wizard', service)
        self.assertNotIn('Before=wizard-setup', service)
        self.assertIn('Nice=19', service)


class CleanupTests(unittest.TestCase):
    def test_factory_removal_uses_wam_and_preserves_onboarding_dependencies(self):
        cleanup = load('factory-cleanup')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            have = {'hermes-agent', 'files', 'transcriber', 'wizard-recorder', 'browser', 'wizard-shell'}
            c = types.SimpleNamespace(runtipi_root=root, runtipi=lambda: None)
            removed = []
            def uninstall(config, app, force=False):
                self.assertIs(config, c)
                self.assertTrue(force)
                removed.append(app)
                have.remove(app)
            cli = types.SimpleNamespace(Config=lambda: c, installed_ids=lambda rt: set(have),
                                        uninstall=uninstall, write_registry=Mock(), STORE='wizardapps')
            for app in ('files', 'retired-app'):
                (root / 'app-data/wizardapps' / app).mkdir(parents=True)
            with patch.dict(sys.modules, {'wam': types.SimpleNamespace(cli=cli)}), \
                 patch.object(cleanup.subprocess, 'run') as remove_data:
                allowed = ['hermes-agent', 'files', 'transcriber']
                self.assertEqual(cleanup.trim(allowed, ['browser', 'wizard-recorder']), ['browser', 'wizard-recorder'])
                self.assertEqual(cleanup.trim(allowed, final=True), ['wizard-shell'])
            remove_data.assert_called_once_with(
                ['sudo', '-n', 'rm', '-rf', '--', str(root / 'app-data/wizardapps/retired-app')], check=True)
            self.assertTrue((root / 'app-data/wizardapps/files').is_dir())
            self.assertEqual(have, set(allowed))
            self.assertEqual(removed, ['browser', 'wizard-recorder', 'wizard-shell'])
            self.assertEqual(cli.write_registry.call_count, 2)

    def test_prune_drops_unused_preloads_but_keeps_live_and_stock_managed_images(self):
        cleanup = load('factory-cleanup')
        calls = []
        def docker(argv, **kwargs):
            calls.append(argv)
            args = argv[1:]
            if args == ['ps', '-aq']:
                return 'container\n'
            if args == ['inspect', 'container']:
                return json.dumps([{'Image': 'live'}])
            if args[:2] == ['image', 'inspect']:
                return json.dumps([{'Id': args[2]}])
            if args[:2] == ['image', 'ls']:
                return 'live\nstock\nmanaged\nrecorder\nhelper\n'
            return ''
        with tempfile.TemporaryDirectory() as tmp, patch.object(cleanup, 'Path', return_value=Path(tmp)), \
             patch.object(cleanup.subprocess, 'check_output', side_effect=docker), patch.object(cleanup.subprocess, 'run'):
            cleanup.prune(['stock', 'managed'])
        removed = {a[-1] for a in calls if a[1:4] == ['image', 'rm', '-f']}
        self.assertEqual(removed, {'recorder', 'helper'})
        self.assertIn(['docker', 'builder', 'prune', '-af'], calls)


class CompactionTests(unittest.TestCase):
    def test_overlapping_and_incomplete_free_inventory_fail_closed(self):
        for ranges in ('2-4, 4-6', '2-5'):
            output = 'Block count: 100\nBlock size: 1024\nFree blocks: 6\n  Free blocks: ' + ranges
            with patch.object(compact.subprocess, 'check_output', return_value=output):
                with self.assertRaises(AssertionError):
                    compact.geometry(Path('unused'), '')

    @unittest.skipUnless(all(shutil.which(x) for x in ('mkfs.ext4', 'e2fsck', 'resize2fs', 'dumpe2fs', 'debugfs')), 'ext4 tools unavailable')
    def test_deleted_nonzero_blocks_are_removed_without_losing_files(self):
        # A 32 MiB test filesystem, not a factory image build. Linux test tools need no mount/root.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image, payload, recovered = root/'tiny.ext4', root/'payload', root/'recovered'
            with image.open('wb') as f:
                f.truncate(32 * 1024**2)
            subprocess.run(['mkfs.ext4', '-q', '-F', image], check=True, capture_output=True)
            payload.write_bytes(os.urandom(1024**2))
            original = hashlib.sha256(payload.read_bytes()).hexdigest()
            for cmd in (f'write {payload} /keep', f'write {payload} /deleted', 'rm /deleted'):
                subprocess.run(['debugfs', '-w', '-R', cmd, image], check=True, capture_output=True)
            stats = compact.compact(image, '', headroom=1024**2)
            self.assertLess(image.stat().st_size, 32 * 1024**2)
            self.assertEqual(stats['bytes'], image.stat().st_size)
            self.assertGreater(stats['freeBlocksZeroed'], 0)
            subprocess.run(['debugfs', '-R', f'dump /keep {recovered}', image], check=True, capture_output=True)
            self.assertEqual(hashlib.sha256(recovered.read_bytes()).hexdigest(), original)


if __name__ == '__main__':
    unittest.main()
