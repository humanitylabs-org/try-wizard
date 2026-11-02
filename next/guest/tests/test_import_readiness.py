"""Production transaction with real snapshot/extraction; only external runtime commands are fake."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'overlay/opt/wizard/bin/wizard-import-hermes'
loader = importlib.machinery.SourceFileLoader('importer', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

class Readiness(unittest.TestCase):
    def scenario(self, failure=None, restore_failure=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / 'data'; data.mkdir(); (data / 'SOUL.md').write_text('original soul')
            (data / '.env').write_text('unchanged secret fixture')
            setup = root / 'setup.json'; setup.write_text(json.dumps({'done': False, 'verified': False, 'brain': {'kind': 'old'}}))
            imports = root / 'imports'; imports.mkdir()
            setup_before = json.loads(setup.read_text())
            def engine(*args, **kw):
                if '--force' in args[1]:
                    (data / 'SOUL.md').write_text('imported soul')
                    return ''
                return json.dumps({'disabled_messaging': [], 'paused_jobs': []})
            starts = 0
            def lifecycle(action):
                nonlocal starts
                if action == 'start':
                    starts += 1
                    return 'error' if (starts == 1 and failure == 'agent') or (starts == 2 and restore_failure) else 'running'
                return 'stopped'
            with patch.multiple(m, ROOT=imports, DATA=data, SETUP_STATE=setup, AGENT_OVERLAY=root/'absent'), \
                 patch.object(m, 'check_and_filter', return_value={'ok': True}), \
                 patch.object(m.os, 'chmod'), patch.object(m, 'engine_image', return_value='test-image'), \
                 patch.object(m, 'wizard_wiring', return_value={}), patch.object(m, 'session_count', return_value=1), \
                 patch.object(m, 'lifecycle', side_effect=lifecycle), patch.object(m, 'in_engine', side_effect=engine), \
                 patch.object(m, 'env_merge', return_value=False), patch.object(m, 'run'), patch.object(m, 'tighten_vm_key'), \
                 patch.object(m, 'wait_api', side_effect=lambda: not (starts == 1 and failure == 'api')), \
                 patch.object(m, 'connect_check', side_effect=lambda: {'ok': not (starts == 1 and failure == 'gateway')}):
                result = m.do_import(root/'input.zip')
            receipt = json.loads((imports/'last.json').read_text())
            if failure:
                self.assertFalse(result['ok'])
                self.assertEqual(result['rolled_back']['ok'], not restore_failure)
                self.assertEqual((data/'SOUL.md').read_text(), 'original soul')
                self.assertEqual((data/'.env').read_text(), 'unchanged secret fixture')
                self.assertEqual(json.loads(setup.read_text()), setup_before)
                self.assertFalse(receipt['complete'])
                self.assertEqual(receipt['restoration_verified'], not restore_failure)
            else:
                self.assertTrue(result['ok']); self.assertTrue(receipt['complete'])
                self.assertTrue(json.loads(setup.read_text())['done'])
    def test_false_agent_rolls_back(self): self.scenario('agent')
    def test_false_api_rolls_back(self): self.scenario('api')
    def test_false_gateway_rolls_back(self): self.scenario('gateway')
    def test_failed_restoration_is_not_success(self): self.scenario('api', True)
    def test_success_commits_only_after_readiness(self): self.scenario()

if __name__ == '__main__': unittest.main()
