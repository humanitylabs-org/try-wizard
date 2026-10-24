"""Focused packaging regressions; WAM and HTTP responses here are explicit test doubles."""
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock
import sys

ROOT = Path(__file__).resolve().parents[1]
cli = types.ModuleType('wam.cli')
cli.STORE = 'wizardapps'
wam = types.ModuleType('wam'); wam.cli = cli; wam.fresh_agent = types.ModuleType('wam.fresh_agent')
with patch.dict(sys.modules, {'wam': wam, 'wam.cli': cli}):
    loader = importlib.machinery.SourceFileLoader('wizard_apps_test', str(ROOT/'overlay/opt/wizard/bin/wizard-apps'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    apps = importlib.util.module_from_spec(spec); loader.exec_module(apps)

class Reply(io.BytesIO):
    def __init__(self, data): super().__init__(json.dumps(data).encode())

class VoiceRecovery(unittest.TestCase):
    def test_status_atomic_and_complete(self):
        with tempfile.TemporaryDirectory() as td, patch.object(apps, 'STATUS', Path(td)/'voice.json'):
            apps.write_status(state='preparing', detail='loading model')
            self.assertEqual(json.loads(apps.STATUS.read_text())['state'], 'preparing')
            apps.write_status(state='ready')
            self.assertEqual(json.loads(apps.STATUS.read_text())['state'], 'ready')
            self.assertEqual([p.name for p in Path(td).iterdir()], ['voice.json'])

    def test_ready_requires_matching_models(self):
        with patch.object(apps, 'engine_container', return_value='test-engine'), patch.object(apps, 'docker', return_value=types.SimpleNamespace(stdout='127.0.0.1')):
            with patch.object(apps.urllib.request, 'urlopen', side_effect=[Reply({'status':'ok'}), Reply({'data':[{'id':'wrong-model'}]})]):
                self.assertNotEqual(apps.voice_health(Path('/nonexistent')).get('status'), 'ok')
            with patch.object(apps.urllib.request, 'urlopen', side_effect=[Reply({'status':'ok'}), Reply({'data':[{'id':apps.VOICE_MODEL}]})]):
                self.assertEqual(apps.voice_health(Path('/nonexistent'))['status'], 'ok')

    def test_wheel_stage_before_engine_listens(self):
        with tempfile.TemporaryDirectory() as td, patch.object(apps, 'engine_container', side_effect=IndexError):
            p=Path(td); (p/'preparation.json').write_text(json.dumps({'stage':'installing Python voice runtime'}))
            self.assertEqual(apps.voice_health(p)['stage'], 'installing Python voice runtime')

    def test_installed_app_is_not_ready_and_no_reinstall(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); image=root/'image'; image.write_text('test-image')
            rt=MagicMock(); rt.wait_status.return_value='running'
            config=types.SimpleNamespace(runtipi_root=root, runtipi=lambda:rt)
            statuses=[]
            with patch.object(cli,'Config',return_value=config,create=True), patch.object(cli,'install',create=True) as install, patch.object(apps,'installed',return_value={'transcriber'}), patch.object(apps,'HERMES_IMAGE_FILE',image), patch.object(apps.subprocess,'run'), patch.object(apps,'docker',return_value=types.SimpleNamespace(stdout='engine-id')), patch.object(apps,'voice_health',side_effect=[{'status':'preparing','stage':'loading model'}, {'status':'ok'}]) as health, patch.object(apps.time,'sleep'), patch.object(apps,'write_status',side_effect=lambda **kw:statuses.append(kw)):
                apps.fetch_voice()
            install.assert_not_called()
            self.assertEqual(health.call_count,2)
            self.assertEqual(statuses[-1]['state'],'ready')
            self.assertTrue(any(s.get('detail')=='loading model' and s['state']!='ready' for s in statuses))
            self.assertTrue(all(s['state']!='ready' for s in statuses[:-1]))

    def test_service_never_trusts_stale_marker(self):
        unit=(ROOT/'overlay/etc/systemd/system/wizard-voice.service').read_text()
        self.assertNotIn('ConditionPathExists=!/var/lib/wizard/voice-installed',unit)
        self.assertNotIn('ExecStopPost=',unit)

if __name__ == '__main__': unittest.main()
