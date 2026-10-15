"""Factory must restore the stock builder after replacing image overrides.
Run: python3 -m unittest discover -s next/tests -p 'test_stock_builder.py'
No Docker/VM needed: execute the real factory with isolated lifecycle boundaries.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'guest/overlay/opt/wizard/bin/wizard-apps'


class StockBuilderFactory(unittest.TestCase):
    def exercise(self, image, fail=False):
        events = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rt = types.SimpleNamespace(
                req=lambda *a, **kw: events.append(a[1]),
                wait_status=lambda *a, **kw: 'running')
            cfg = types.SimpleNamespace(runtipi_root=root, runtipi=lambda: rt)
            cli = types.SimpleNamespace(Config=lambda: cfg, STORE='wizardapps',
                installed_ids=lambda _: [], write_registry=lambda *a: events.append('registry'))
            def fresh(args):
                self.assertEqual(args, ['fresh', '--restart'])
                if image:
                    self.assertIn(image, (root/'user-config/wizardapps/hermes-agent/docker-compose.yml').read_text())
                    self.assertIn('ssh', events)
                events.append('builder')
                return int(fail)
            wam = types.ModuleType('wam')
            wam.cli = cli
            wam.builder_bundle = types.SimpleNamespace(main=fresh)
            loader = importlib.machinery.SourceFileLoader('factory_under_test', str(SCRIPT))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            mod = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {'wam': wam}), patch.object(sys, 'path', list(sys.path)):
                loader.exec_module(mod)
                def docker(*args, **kwargs):
                    events.append(('docker', args))
                    return types.SimpleNamespace(returncode=0, stdout=image or '', stderr='')
                with patch.object(mod, 'docker', docker), patch.object(mod.subprocess, 'run'), \
                     patch.object(mod, 'shared_vm_terminal', lambda *a: events.append('ssh')), \
                     patch.object(mod, 'say'):
                    if fail:
                        with self.assertRaisesRegex(SystemExit, 'stock builder provisioning failed'):
                            mod.factory(image)
                        self.assertNotIn('registry', events)
                    else:
                        mod.factory(image)
                        self.assertLess(events.index('builder'), events.index('registry'))
        return events

    def test_slim_image_restores_builder_after_ssh_and_override(self):
        self.exercise('example.invalid/hermes:pin')

    def test_default_image_also_provisions_builder(self):
        self.exercise(None)

    def test_builder_failure_prevents_factory_success(self):
        self.exercise('example.invalid/hermes:pin', fail=True)


if __name__ == '__main__':
    unittest.main()
