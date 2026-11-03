"""Production coordinator/installer regressions with explicit fake WAM/Docker.
These fixtures are not runtime/ARM/model/transcription acceptance.
"""
import concurrent.futures
import fcntl
import importlib.util
import importlib.machinery
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import MagicMock, patch
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
VOICE = ROOT/'overlay/opt/wizard/voice'

def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    return module

r = load('voice_reconcile_test', VOICE/'reconcile.py')
i = load('voice_install_test', VOICE/'install.py')
cli = types.ModuleType('wam.cli'); cli.STORE = 'wizardapps'
wam = types.ModuleType('wam'); wam.cli = cli; wam.fresh_agent = types.ModuleType('wam.fresh_agent')
with patch.dict(sys.modules, {'wam': wam, 'wam.cli': cli}):
    apps = load('voice_apps_test', ROOT/'overlay/opt/wizard/bin/wizard-apps')
SELECTED = {'schema': 1, 'api':'speaches-0.9', 'provider':'local', 'model':r.MODEL,
            'revision':'0bbb45a3365852604aef28b538a8f066f4ccaa85', 'quantization':'int8',
            'image':'ghcr.io/example/engine@sha256:'+'a'*64,
            'bindings':{'transcriber-engine':'ghcr.io/example/engine@sha256:'+'a'*64,
                        'transcriber':'ghcr.io/example/helper@sha256:'+'b'*64}}
ROW = {'Id':'cid', 'Image':'image-id', 'State':{'Running':True}, 'Config':{'Entrypoint':['uvicorn']},
       'NetworkSettings':{'Networks':{'private':{'IPAddress':'172.18.0.2'}}}}

def reply(data, rc=0): return types.SimpleNamespace(returncode=rc, stdout=json.dumps(data), stderr='')

class VoiceRecovery(unittest.TestCase):
    def test_status_atomic_and_complete(self):
        with tempfile.TemporaryDirectory() as td, patch.object(apps,'STATUS',Path(td)/'voice.json'):
            apps.write_status(state='preparing'); apps.write_status(state='ready')
            self.assertEqual(json.loads(apps.STATUS.read_text())['state'],'ready')
            self.assertEqual(len(list(Path(td).iterdir())),1)

    def test_service_rechecks_without_terminal_restart_loop(self):
        unit=(ROOT/'overlay/etc/systemd/system/wizard-voice.service').read_text()
        self.assertIn('Type=oneshot',unit); self.assertIn('Restart=no',unit)
        self.assertNotIn('ExecStartPre=',unit); self.assertNotIn('voice-installed',unit)

    def test_fetch_does_not_consume_hermes_image(self):
        import inspect
        source=inspect.getsource(apps.fetch_voice)
        self.assertNotIn('HERMES_IMAGE',source); self.assertNotIn('VOICE_OVERRIDE',source)
        self.assertNotIn('restart',source.lower())

    def test_running_selected_no_lifecycle(self): self.scenario('running')
    def test_stopped_selected_uses_wam_start(self): self.scenario('stopped')
    def test_absent_installs_through_wam(self): self.scenario('absent')
    def test_repeat_running_no_lifecycle(self): self.scenario('running', repeat=2)

    def scenario(self, state, repeat=1):
        with tempfile.TemporaryDirectory() as td:
            c=types.SimpleNamespace(runtipi_root=Path(td),runtipi=MagicMock())
            fakecli=types.SimpleNamespace(STORE='wizardapps',install=MagicMock())
            initial=json.loads(json.dumps(ROW)); initial['State']['Running']=state!='stopped'
            rows=[initial, ROW, ROW] if state!='absent' else [None, ROW, ROW]
            def docker(*args):
                self.assertEqual(args[:2],('image','inspect'))
                return reply({'unused':True}) if False else reply([{'Id':'image-id','RepoDigests':list(SELECTED['bindings'].values())}])
            with patch.object(r,'migrate_override',return_value=False) as migrate, patch.object(r,'engine',side_effect=rows*repeat), patch.object(r,'health',return_value={'status':'ok'}), patch.object(r,'verify_model_runtime') as verify, patch.object(r,'get_json',return_value={'models':[r.MODEL]}):
                for _ in range(repeat):
                    r.reconcile(c,fakecli,docker,lambda _c:set() if state=='absent' else {'transcriber'},SELECTED,MagicMock())
            self.assertEqual(migrate.call_count,repeat); self.assertEqual(verify.call_count,repeat)
            if state=='running': fakecli.install.assert_not_called(); c.runtipi.assert_not_called()
            elif state=='stopped': c.runtipi.return_value.req.assert_called_once_with('POST','/app-lifecycle/transcriber:wizardapps/start',{},timeout=300)
            else: fakecli.install.assert_called_once_with(c,'transcriber',{'TRANSCRIBER_MODEL':r.MODEL})

    def test_model_mismatch_terminal(self):
        with self.assertRaisesRegex(r.Refusal,'required Parakeet model'):
            r.health(ROW,get=lambda url: {'message':'OK'} if url.endswith('health') else {'data':[{'id':'wrong'}]})

    def test_ambiguous_speech_model_selection_refused(self):
        with self.assertRaisesRegex(r.Refusal,'only selected speech model'):
            r.health(ROW,get=lambda url:{'message':'OK'} if url.endswith('health') else {'data':[{'id':'other'},{'id':r.MODEL}]})

    def test_unsupported_health_terminal(self):
        with self.assertRaisesRegex(r.Refusal,'contract is unsupported'):
            r.health(ROW,get=lambda _: {'status':'ok'})

    def test_exact_speaches_health_contract(self):
        self.assertEqual(r.health(ROW,get=lambda url:{'message':'OK'} if url.endswith('health') else {'data':[{'id':r.MODEL}]})['model'],r.MODEL)

    def test_model_listing_not_runtime_proof(self):
        with self.assertRaisesRegex(r.Refusal,'pinned Parakeet runtime'):
            r.verify_model_runtime(lambda *a:reply({},rc=1),ROW)

    def test_wrong_running_image_refused(self):
        docker=MagicMock(side_effect=[types.SimpleNamespace(returncode=0,stdout='cid'),reply([dict(ROW,Image='wrong')])])
        with self.assertRaisesRegex(r.Refusal,'security selection'): r.engine(docker,'image-id')
        self.assertEqual(docker.call_count,2)

    def test_ambiguous_containers_refused(self):
        with self.assertRaisesRegex(r.Refusal,'More than one'):
            r.engine(lambda *a:types.SimpleNamespace(returncode=0,stdout='one\ntwo'),'image-id')

    def test_legacy_entrypoint_refused(self):
        row=dict(ROW,Config={'Entrypoint':['sh','/voice/start.sh']})
        with self.assertRaisesRegex(r.Refusal,'Legacy'):
            r.engine(MagicMock(side_effect=[types.SimpleNamespace(returncode=0,stdout='cid'),reply([row])]),'image-id')

    def test_public_network_refused(self):
        row=json.loads(json.dumps(ROW)); row['NetworkSettings']['Networks']['private']['IPAddress']='8.8.8.8'
        with self.assertRaises(r.Refusal): r.origin(row)

    def test_legacy_override_migrated_both_security_images(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'docker-compose.yml'; raw=apps.VOICE_OVERRIDE.format(image='old-hermes').encode();p.write_bytes(raw)
            self.assertTrue(r.migrate_override(p,SELECTED)); self.assertEqual(yaml.safe_load(p.read_text()),r.binding_document(SELECTED))
            self.assertEqual(next(p.parent.glob('*.bak')).read_bytes(),raw)
            before=p.read_bytes();self.assertFalse(r.migrate_override(p,SELECTED));self.assertEqual(p.read_bytes(),before)

    def test_unknown_security_fields_preserved_and_refused(self):
        for key,value in [('privileged',True),('security_opt',['no-new-privileges:true']),('cap_drop',['ALL']),('volumes',['/private:/data:ro'])]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as td:
                p=Path(td)/'docker-compose.yml';doc=r.binding_document(SELECTED);doc['services']['transcriber-engine'][key]=value
                raw=yaml.safe_dump(doc).encode();p.write_bytes(raw)
                with self.assertRaises(r.Refusal): r.migrate_override(p,SELECTED)
                self.assertEqual(p.read_bytes(),raw)

    def test_legacy_with_foreign_key_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'docker-compose.yml';p.write_text(apps.VOICE_OVERRIDE.format(image='hermes')+'    privileged: true\n');before=p.read_bytes()
            with self.assertRaises(r.Refusal):r.migrate_override(p,SELECTED)
            self.assertEqual(p.read_bytes(),before)

    def test_symlink_binding_refused(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'target';target.write_text('untouched'); p=Path(td)/'binding';p.symlink_to(target)
            with self.assertRaises(r.Refusal):r.migrate_override(p,SELECTED)
            self.assertEqual(target.read_text(),'untouched')

    def test_missing_binding_refused(self):
        with self.assertRaises(r.Refusal):r.migrate_override(Path('/nonexistent/test/voice'),SELECTED)

    def test_crash_after_backup_repeat_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'docker-compose.yml';raw=apps.VOICE_OVERRIDE.format(image='hermes').encode();p.write_bytes(raw)
            real=r.atomic
            def fail(path,*args,**kw):
                if path==p:raise OSError('injected')
                return real(path,*args,**kw)
            with patch.object(r,'atomic',side_effect=fail),self.assertRaises(OSError):r.migrate_override(p,SELECTED)
            self.assertEqual(p.read_bytes(),raw);self.assertTrue(r.migrate_override(p,SELECTED))

    def test_backup_conflict_refused(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'docker-compose.yml';raw=apps.VOICE_OVERRIDE.format(image='hermes').encode();p.write_bytes(raw)
            p.with_name('docker-compose.legacy-'+hashlib.sha256(raw).hexdigest()+'.bak').write_text('conflict')
            with self.assertRaises(r.Refusal):r.migrate_override(p,SELECTED)
            self.assertEqual(p.read_bytes(),raw)

    def test_contract_from_final_security_plan(self):
        plan={'resolutions':{'engine':{'image':SELECTED['image']},'helper':{'image':SELECTED['bindings']['transcriber']}}}
        bindings={'bindings':[{'app':'transcriber','service':s,'target':'engine' if s.endswith('engine') else 'helper'} for s in SELECTED['bindings']]}
        self.assertEqual(r.contract_from_plan(plan,bindings),SELECTED)

    def test_incomplete_security_plan_refused(self):
        with self.assertRaises(r.Refusal):r.contract_from_plan({'resolutions':{}},{'bindings':[]})

    def test_concurrent_retry_one_writer(self):
        with tempfile.TemporaryDirectory() as td:
            lock=Path(td)/'lock'; entered=threading.Event(); release=threading.Event();statuses=[]
            def work(*args):entered.set();self.assertTrue(release.wait(3));return {'status':'ok'}
            with patch.object(r,'selection',return_value=SELECTED),patch.object(r,'reconcile',side_effect=work) as reconcile,concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                future=pool.submit(r.run,None,None,None,None,lambda **v:statuses.append(v),lock=lock)
                self.assertTrue(entered.wait(3));self.assertEqual(r.run(None,None,None,None,MagicMock(),lock=lock),{'busy':True});release.set();future.result()
            self.assertEqual(reconcile.call_count,1);self.assertEqual(statuses[-1]['state'],'ready')

    def test_refusal_not_ready(self):
        with tempfile.TemporaryDirectory() as td,patch.object(r,'selection',side_effect=r.Refusal('compatible update required')):
            statuses=[];result=r.run(None,None,None,None,lambda **v:statuses.append(v),lock=Path(td)/'lock')
            self.assertIn('error',result);self.assertEqual(statuses[-1]['state'],'error')

    def test_lock_symlink_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'lock';p.symlink_to(Path(td)/'target')
            with self.assertRaises(OSError):r.run(None,None,None,None,MagicMock(),lock=p)

    def test_atomic_failure_leaves_original(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'file';p.write_bytes(b'old')
            with patch.object(r.os,'replace',side_effect=OSError('injected')),self.assertRaises(OSError):r.atomic(p,b'new')
            self.assertEqual(p.read_bytes(),b'old');self.assertEqual(len(list(p.parent.iterdir())),1)

    def test_protected_selection_refuses_user_owned_path(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'selected';p.write_text(json.dumps(SELECTED))
            if os.getuid()!=0:
                with self.assertRaises(r.Refusal):r.selection(p)

    def test_upgrade_rollback_code_bindings_and_sentinels(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'guest';payload=Path(td)/'payload';root.mkdir();payload.mkdir()
            old={}
            for rel in i.FILES:
                src=ROOT/'overlay'/rel;dst=payload/'overlay'/rel;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(src.read_bytes())
                target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(('old '+rel).encode());old[rel]=target.read_bytes()
            binding=root/i.BINDING;binding.parent.mkdir(parents=True);binding.write_text(apps.VOICE_OVERRIDE.format(image='hermes'));old_binding=binding.read_bytes()
            sentinel=root/'owner-data';sentinel.write_text('synthetic sentinel')
            (payload/'selected-engine.json').write_text(json.dumps(SELECTED))
            module=i.load_reconciler(payload)
            with patch.object(i,'load_reconciler',return_value=module),patch.object(module,'selection',return_value=SELECTED):
                run=MagicMock();result=i.install(payload,root,run);self.assertFalse(result['imageStoreMutated'])
                self.assertEqual(yaml.safe_load(binding.read_text()),r.binding_document(SELECTED))
                before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
                self.assertTrue(i.install(payload,root,run)['alreadyInstalled']);self.assertEqual(before,{p:p.read_bytes() for p in root.rglob('*') if p.is_file()})
                self.assertTrue(i.rollback(root,run)['coordinatorDisabled'])
            for rel,raw in old.items():self.assertEqual((root/rel).read_bytes(),raw)
            self.assertEqual(binding.read_bytes(),old_binding);self.assertEqual(sentinel.read_text(),'synthetic sentinel')
            self.assertFalse((root/i.CONTRACT).exists())
            self.assertEqual((root/i.FENCE).read_bytes(),i.FENCE_BYTES)
            self.assertFalse((root/'var/lib/wizard/voice-rollback-approved').exists())
            self.assertFalse((root/i.BACKUP/'receipt.json').exists())
            self.assertFalse(any('docker' in str(call) for call in run.call_args_list))

if __name__=='__main__':unittest.main()
