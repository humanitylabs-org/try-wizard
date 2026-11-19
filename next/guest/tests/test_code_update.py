#!/usr/bin/env python3
"""A Mac release carries a code-only guest update, and the guest installs only that (try-wizard#123).

Builds the payload the release workflow builds (next/guest/build-code-payload.py), then runs the guest-side installer
(next/guest/code-update.py) against a fake guest root with stubbed systemctl/nginx/docker, and checks its receipt with
the Host's own fixed check (next/mac/Shared/GuestPatchCommand.swift).
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

GUEST = Path(__file__).resolve().parents[1]
ROOT = GUEST.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('build_code_payload', GUEST / 'build-code-payload.py')
installer = load('code_update', GUEST / 'code-update.py')


def host_check():
    source = (ROOT / 'next/mac/Shared/GuestPatchCommand.swift').read_text()
    return textwrap.dedent(source[source.index("    assert d['patch']"):source.index("    print('WIZARD_PATCH_OK")])


class Stub:
    """systemctl, nginx and docker as the guest would answer them."""
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def run(self, args, **kw):
        self.calls.append(list(args))
        if self.fail and self.fail in ' '.join(args):
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0)

    def check_output(self, args, **kw):
        self.calls.append(list(args))
        if args[:2] == ['docker', 'ps']:
            return 'c0ffee\n'
        if args[:2] == ['docker', 'inspect']:
            return 'sha256:' + 'a' * 64 + '\n'
        raise AssertionError('unexpected command %r' % (args,))


class CodeOnlyPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.payload = self.tmpdir / 'payload'
        self.bom = builder.build(self.payload, 'f' * 40)

    def test_carries_the_setup_page_and_the_window_door_only(self):
        files = set(self.bom['files'])
        self.assertEqual(self.bom['kind'], 'code-only')
        for need in ('source/next/guest/upgrade-mvp-stack.py', 'source/next/guest/code-update.py',
                     'source/next/guest/stack-preservation.py',
                     'overlay/opt/wizard/setup/server.py', 'overlay/opt/wizard/setup/static/index.html',
                     'overlay/opt/wizard/local-proxy.conf', 'overlay/opt/wizard/local-proxy-owner.inc',
                     'overlay/opt/wizard/bin/wizard-local-routes', 'overlay/opt/wizard/bin/wizard-shell-port',
                     'overlay/etc/systemd/system/wizard-local-proxy.service',
                     'overlay/etc/systemd/system/wizard-local-routes.timer'):
            self.assertIn(need, files)
        for path in files:
            self.assertNotIn('/tests/', path)
            self.assertNotIn('/testing/', path)
            self.assertNotIn('__pycache__', path)
            self.assertNotIn('product-plugin', path)
            self.assertNotIn('wizard-runtime-configure', path)
        # No images, no cold bootstrap (the app refuses a legacy cold upgrade without it, before touching the disk).
        self.assertFalse(any(p.endswith('.tar') for p in files))
        self.assertNotIn('source/next/guest/cold-bootstrap.py', files)
        size = sum((self.payload / f).stat().st_size for f in files)
        self.assertLess(size, 5_000_000)
        installer.verify(self.payload)

    def test_tampered_extra_or_outside_files_are_refused(self):
        target = self.payload / 'overlay/opt/wizard/local-proxy.conf'
        original = target.read_bytes()
        target.write_bytes(original + b'#')
        with self.assertRaisesRegex(SystemExit, 'mismatch'):
            installer.verify(self.payload)
        target.write_bytes(original)
        extra = self.payload / 'overlay/opt/wizard/bin/extra'
        extra.write_text('x')
        with self.assertRaisesRegex(SystemExit, 'not in its BOM'):
            installer.verify(self.payload)
        extra.unlink()
        bom = json.loads((self.payload / 'runtime-bom.json').read_text())
        (self.payload / 'overlay/etc/sudoers.d').mkdir(parents=True)
        (self.payload / 'overlay/etc/sudoers.d/x').write_text('x')
        bom['files']['overlay/etc/sudoers.d/x'] = builder.sha(self.payload / 'overlay/etc/sudoers.d/x')
        (self.payload / 'runtime-bom.json').write_text(json.dumps(bom))
        with self.assertRaisesRegex(SystemExit, 'may not write'):
            installer.verify(self.payload)


class CodeOnlyInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.payload, self.root = t / 'payload', t / 'guest'
        builder.build(self.payload, 'f' * 40)
        data = self.root / installer.HERMES_DATA
        data.mkdir(parents=True)
        (data / 'SOUL.md').write_text('soul')
        (data / '.env').write_text('OPENROUTER_API_KEY=fixture\n')
        (data / 'auth.json').write_text(json.dumps({'providers': {}}))
        self.data = data
        conf = self.root / 'opt/wizard/local-proxy.conf'
        conf.parent.mkdir(parents=True)
        conf.write_text('# 0.4.0 config\n')

    def receipt(self):
        return json.loads((self.root / 'var/lib/wizard/patches/mac-stack-v1/applied.json').read_text())

    def test_installs_files_restarts_only_window_door_and_setup_and_passes_the_host_check(self):
        stub = Stub()
        self.assertEqual(installer.apply(self.payload, root=self.root, run=stub.run, check_output=stub.check_output), 0)
        conf = self.root / 'opt/wizard/local-proxy.conf'
        self.assertEqual(conf.read_bytes(), (GUEST / 'overlay/opt/wizard/local-proxy.conf').read_bytes())
        routes = self.root / 'opt/wizard/bin/wizard-local-routes'
        self.assertEqual(stat.S_IMODE(routes.stat().st_mode), 0o755)
        unit = self.root / 'etc/systemd/system/wizard-local-proxy.service'
        self.assertEqual(stat.S_IMODE(unit.stat().st_mode), 0o644)
        self.assertIn('ExecStartPre=/opt/wizard/bin/wizard-local-routes', unit.read_text())
        # The replaced config is kept in the guest's private patch folder.
        kept = list((self.root / 'var/lib/wizard/patches/mac-stack-v1').glob('code-only-previous-*/opt/wizard/local-proxy.conf'))
        self.assertEqual([k.read_text() for k in kept], ['# 0.4.0 config\n'])
        calls = [' '.join(c) for c in stub.calls]
        self.assertLess(calls.index('systemctl daemon-reload'), calls.index('systemctl restart wizard-local-proxy wizard-setup'))
        nginx = [i for i, c in enumerate(calls) if c.startswith('/usr/sbin/nginx -t')]
        self.assertEqual(len(nginx), 1)
        self.assertLess(nginx[0], calls.index('systemctl restart wizard-local-proxy wizard-setup'))
        self.assertIn('systemctl enable wizard-local-routes.timer', calls)
        # Nothing touches images, the agent or the App Manager.
        for c in calls:
            self.assertNotIn('docker load', c)
            self.assertNotIn('docker restart', c)
            self.assertNotIn('wam', c)
            self.assertNotIn('wizard-product-configure', c)
            self.assertNotIn('wizard-app-manager-api', c)
        receipt = self.receipt()
        self.assertEqual(receipt['kind'], 'code-only')
        self.assertNotIn('managed_runtime_image', receipt)
        exec(host_check(), {'d': receipt})

    def test_keeps_naming_the_managed_runtime_an_earlier_full_update_installed(self):
        (self.root / 'opt/wizard/managed-runtime.json').write_text(json.dumps({'image': 'sha256:managed'}))
        stub = Stub()
        installer.apply(self.payload, root=self.root, run=stub.run, check_output=stub.check_output)
        self.assertEqual(self.receipt()['managed_runtime_image'], 'sha256:managed')

    def test_a_bad_window_door_config_fails_before_the_restart_and_leaves_no_receipt(self):
        stub = Stub(fail='nginx')
        with self.assertRaises(subprocess.CalledProcessError):
            installer.apply(self.payload, root=self.root, run=stub.run, check_output=stub.check_output)
        self.assertNotIn(['systemctl', 'restart', 'wizard-local-proxy', 'wizard-setup'], stub.calls)
        self.assertFalse((self.root / 'var/lib/wizard/patches/mac-stack-v1/applied.json').exists())

    def test_changed_soul_or_env_leaves_no_receipt(self):
        for name in ('SOUL.md', '.env'):
            stub = Stub()
            def run(args, _name=name, **kw):
                if args[:2] == ['systemctl', 'restart']:
                    (self.data / _name).write_text('changed')
                return stub.run(args, **kw)
            with self.assertRaisesRegex(SystemExit, 'Protected state'):
                installer.apply(self.payload, root=self.root, run=run, check_output=stub.check_output)
            self.assertFalse((self.root / 'var/lib/wizard/patches/mac-stack-v1/applied.json').exists())
            (self.data / 'SOUL.md').write_text('soul')
            (self.data / '.env').write_text('OPENROUTER_API_KEY=fixture\n')

    def test_symlinked_install_folder_is_refused(self):
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (self.root / 'etc/systemd').mkdir(parents=True)
        (self.root / 'etc/systemd/system').symlink_to(outside, target_is_directory=True)
        stub = Stub()
        with self.assertRaisesRegex(RuntimeError, 'Symlink'):
            installer.apply(self.payload, root=self.root, run=stub.run, check_output=stub.check_output)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(stub.calls, [])

    def test_legacy_cold_bootstrap_is_refused_before_any_change(self):
        stub = Stub()
        with self.assertRaisesRegex(SystemExit, 'legacy disk'):
            installer.apply(self.payload, cold_bootstrap=True, root=self.root, run=stub.run, check_output=stub.check_output)
        self.assertEqual(stub.calls, [])
        self.assertFalse((self.root / 'var/lib/wizard').exists())


class FixedEntryPoint(unittest.TestCase):
    """The Host runs upgrade-mvp-stack.py; with a code-only BOM it must not ask for the full payload's images."""
    def test_dispatches_a_code_only_payload_to_the_code_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            payload = tmp / 'payload'
            builder.build(payload, 'f' * 40)
            fake = tmp / 'runtipi'
            (fake / 'app-data/wizardapps/hermes-agent/data').mkdir(parents=True)
            (fake / 'app-data/wizardapps/hermes-agent/data/config.yaml').write_text('model: x\n')
            script = payload / 'source/next/guest/upgrade-mvp-stack.py'
            source = script.read_text().replace("'/home/wizard/runtipi'", repr(str(fake)))
            self.assertLess(source.index("'kind')=='code-only'"), source.index("for required in ("))
            out = tmp / 'out.txt'
            with mock.patch.dict(sys.modules, {'yaml': types.ModuleType('yaml')}), \
                    mock.patch.object(os, 'geteuid', return_value=0), \
                    mock.patch.object(sys, 'argv', [str(script), str(payload)]), \
                    open(out, 'w') as stdout, mock.patch.object(sys, 'stdout', stdout):
                with self.assertRaises(SystemExit) as done:
                    exec(compile(source, str(script), 'exec'), {'__name__': '__main__', '__file__': str(script)})
            self.assertEqual(done.exception.code, 0)
            self.assertIn('Preflight passed: code-only guest update', out.read_text())


if __name__ == '__main__':
    unittest.main()
