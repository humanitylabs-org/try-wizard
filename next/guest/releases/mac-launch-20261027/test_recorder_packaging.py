"""Synthetic control-plane tests, not substitutes for Thales build/TLS receipts."""
import contextlib, importlib.util, io, json, os, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch
import local_oci as oci
from test_local_oci import fixture_archive
HERE=Path(__file__).resolve().parent

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    assert spec and spec.loader
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

core_package=module('recorder_core_contract','package-image.py')
security_package=module('recorder_security_contract','package-security-image.py')

class RecorderPackagingTests(unittest.TestCase):
    def setUp(self):
        self.pins=json.loads((HERE/'pins.json').read_text())
        self.target=next(t for t in json.loads((HERE/'security-image-plan.json').read_text())['targets'] if t['key']=='recorder')
    def core(self,root):
        row=fixture_archive(root,self.target['baseRef'],'recorder-source')
        row.update(component='recorder',sourceCommit=self.pins['finalPins']['recorder'])
        path=root/'image-packaging/recorder/result.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(row))
        return row,path
    def test_local_dependency_binds_source_and_archive(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();row,path=self.core(root)
            actual,dependency=oci.local_base(root,self.target,self.pins)
            self.assertEqual(actual,row);self.assertEqual(dependency['receiptSha256'],oci.sha(path))
            self.assertEqual(dependency['digest'],row['digest'])
            row['sourceCommit']='0'*40;path.write_text(json.dumps(row))
            with self.assertRaises(AssertionError):oci.local_base(root,self.target,self.pins)
    def test_missing_local_dependency_never_falls_back(self):
        with tempfile.TemporaryDirectory() as d,patch.object(oci,'run') as run:
            with self.assertRaises(FileNotFoundError):oci.local_base(Path(d),self.target,self.pins)
            run.assert_not_called()
    def test_security_loads_core_without_pull_and_records_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();row,path=self.core(root)
            obj={'Architecture':'arm64','Config':{'User':'1000:1000','Entrypoint':['/usr/bin/tini','--'],'Cmd':['python','supervise.py'],'WorkingDir':'/app','Labels':{'source':'fixture'}}}
            inventory={'nodeMajor':22,'alpine':False,'claude':False,'minimal':False,'browser':False}
            built=fixture_archive(root,'ghcr.io/humanitylabs-org/wizard-mac-security-recorder','recorder-derived')
            built['archive']=str(root/built['archive'])
            with contextlib.ExitStack() as s:
                s.enter_context(patch.object(security_package.sys,'argv',['package-security-image.py','--stage-root',str(root),'--target','recorder']))
                s.enter_context(patch.object(security_package.sys,'platform','darwin'))
                s.enter_context(patch.dict(os.environ,THALES_MEDIA=str(root)))
                s.enter_context(patch.object(oci,'environment',return_value={}))
                load=s.enter_context(patch.object(oci,'load',return_value=obj))
                s.enter_context(patch.object(oci,'export',return_value=(built,obj)))
                s.enter_context(patch.object(oci,'mirror',side_effect=lambda ref,*_:ref))
                s.enter_context(patch.object(oci,'probe_mount',return_value=contextlib.nullcontext('fixture-volume:/opt/wizard-probe:ro')))
                s.enter_context(patch.object(security_package,'wheel'))
                s.enter_context(patch.object(security_package.subprocess,'run',return_value=types.SimpleNamespace(stdout=json.dumps(inventory))))
                run=s.enter_context(patch.object(security_package,'run',side_effect=[json.dumps([obj]),'{}']))
                s.enter_context(contextlib.redirect_stdout(io.StringIO()))
                security_package.main()
            load.assert_called_once();self.assertEqual(load.call_args.args[1],row)
            self.assertFalse(any('pull' in c.args[0] for c in run.call_args_list))
            result=json.loads((root/'security-packaging/recorder/result.json').read_text())
            self.assertEqual(result['base'],row['ref']+'@'+row['digest'])
            self.assertEqual(result['baseDependency']['receiptSha256'],oci.sha(path))
    def test_core_context_is_repo_root_with_debian_recipe(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();source=root/'inputs/recorder';(source/'app').mkdir(parents=True)
            (source/'.wizard-source.json').write_text(json.dumps({'commit':self.pins['finalPins']['recorder']}))
            (source/'app/Dockerfile').write_text('FROM node:22-bookworm-slim AS node\nFROM python:3.12-slim-bookworm\nCOPY app/test.py /app/\nUSER 1000:1000\nWORKDIR /app\n')
            (source/'app/test.py').write_text('# unit fixture\n')
            def export(out,context,image,env,extra):
                text=(context/'Dockerfile').read_text()
                self.assertTrue((context/'app/test.py').exists());self.assertNotIn('apk ',text)
                self.assertIn('apt-get ',text);self.assertIn('node -e',text)
                self.assertTrue(text.endswith('USER 1000:1000\n'))
                self.assertEqual(image,self.target['baseRef'])
                self.assertIn('org.opencontainers.image.revision='+self.pins['finalPins']['recorder'],extra)
                return {'archive':str(out/'unit.oci.tar')},{'Config':{'Labels':{'org.opencontainers.image.revision':self.pins['finalPins']['recorder']}}}
            with contextlib.ExitStack() as s:
                s.enter_context(patch.object(core_package.sys,'argv',['package-image.py','--stage-root',str(root),'--component','recorder']))
                s.enter_context(patch.object(core_package.sys,'platform','darwin'))
                s.enter_context(patch.dict(os.environ,THALES_MEDIA=str(root)))
                s.enter_context(patch.object(oci,'environment',return_value={}))
                mirror=s.enter_context(patch.object(oci,'mirror',side_effect=lambda ref,*_:'mirror.gcr.io/library/'+ref.split(':')[0]+'@sha256:'+'a'*64))
                s.enter_context(patch.object(oci,'export',side_effect=export))
                s.enter_context(contextlib.redirect_stdout(io.StringIO()));core_package.main()
            self.assertEqual(mirror.call_args_list[0].args[0],'node:22.23.4-bookworm-slim')
            result=json.loads((root/'image-packaging/recorder/result.json').read_text())
            self.assertEqual(result['sourceCommit'],self.pins['finalPins']['recorder'])
    def test_runtipi_recorder_binding_selects_local_security_digest(self):
        apply=module('recorder_guest_apply','guest-security-apply.py')
        plan=json.loads((HERE/'security-image-plan.json').read_text())
        image='ghcr.io/humanitylabs-org/wizard-mac-security-recorder@sha256:'+'a'*64
        plan['resolutions']={t['key']:{'image':image} for t in plan['targets']}
        inherited=[{'Config':{'Labels':{'com.docker.compose.service':service}}} for service in ['wizard-shell','runtipi']]
        with tempfile.TemporaryDirectory() as td,patch.object(apply,'ROOT',Path(td)),patch.object(apply,'PREP',HERE),patch.object(apply.store,'containers',return_value=[]),patch.object(apply.store,'inherited',return_value=inherited),patch.object(apply,'merge',side_effect=lambda path,updates:{'path':str(path),'images':updates}):
            root=Path(td)
            # No retained infrastructure containers in this synthetic fixture; test only app writes.
            plan['targets']=[t for t in plan['targets'] if t['key'] not in {'postgres','rabbitmq','traefik'}]
            (root/'assembly-work').mkdir(exist_ok=True)
            (root/'assembly-work/factory-overlays.json').write_text(json.dumps({'removed':[]}))
            writes=apply.prepare(plan)
        recorder=next(w for w in writes if '/wizard-recorder/' in w['path'])
        self.assertEqual(recorder['images'],{'wizard-recorder':image})

if __name__=='__main__':unittest.main()
