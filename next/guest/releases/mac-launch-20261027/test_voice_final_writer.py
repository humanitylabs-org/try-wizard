"""Exact final-writer source fakes. Supply VOICE_NATIVE_SOURCE pinned archive.
No Docker, VM, image load, model download, or real systemctl is used here.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock,patch
import yaml

HERE=Path(__file__).resolve().parent
if not os.environ.get('VOICE_NATIVE_SOURCE'):
    raise unittest.SkipTest('VOICE_NATIVE_SOURCE must name the frozen native archive for final-writer tests')
NATIVE=Path(os.environ['VOICE_NATIVE_SOURCE'])/'next/guest'
sys.path.insert(0,str(HERE))

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

factory=load('voice_final_writer',HERE/'guest-security-apply.py')
r=load('voice_common_factory_test',NATIVE/'overlay/opt/wizard/voice/reconcile.py')
i=load('voice_installer_factory_test',NATIVE/'overlay/opt/wizard/voice/install.py')
SELECTED=json.loads((NATIVE/'releases/mac-launch-20261027/voice-selected-engine.json').read_text())
PLAN={'resolutions':{'engine':{'image':SELECTED['image']},'helper':{'image':SELECTED['bindings']['transcriber']}}}
BINDINGS={'bindings':[{'app':'transcriber','service':service,'target':'engine' if service.endswith('engine') else 'helper'} for service in SELECTED['bindings']]}

class FactoryVoice(unittest.TestCase):
    def fixture(self,root):
        launch=root/'launch';guest=root/'guest'
        native=launch/'final/native/next/guest'
        for rel in i.FILES:
            dst=native/'overlay'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(NATIVE/'overlay'/rel,dst)
            dest=guest/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text('retained '+rel)
        selected=native/'releases/mac-launch-20261027/voice-selected-engine.json';selected.parent.mkdir(parents=True);shutil.copy2(NATIVE/'releases/mac-launch-20261027/voice-selected-engine.json',selected)
        prep=launch/'preparation';prep.mkdir();(prep/'security-compose-bindings.json').write_text(json.dumps(BINDINGS))
        binding=guest/i.BINDING;binding.parent.mkdir(parents=True);binding.write_text(yaml.safe_dump(r.binding_document(SELECTED)))
        return launch,guest

    def test_factory_contract_equal_normal_update(self):
        self.assertEqual(r.contract_from_plan(PLAN,BINDINGS),SELECTED)

    def test_final_writer_uses_real_component_and_keeps_selection(self):
        with tempfile.TemporaryDirectory() as td:
            launch,guest=self.fixture(Path(td));run=MagicMock();actual=i.install
            def native_module(name):return i if name=='install.py' else r
            with patch.object(factory,'ROOT',launch),patch.object(factory,'PREP',launch/'preparation'),patch.object(factory,'native_module',side_effect=native_module),patch.object(i,'load_reconciler',return_value=r),patch.object(r,'selection',return_value=SELECTED),patch.object(i,'install',side_effect=lambda p:actual(p,guest,run)):
                receipt=factory.finalize_voice(PLAN)
            self.assertFalse(receipt['imageStoreMutated']);self.assertFalse(receipt['engineLifecycleMutated'])
            self.assertEqual((guest/i.CONTRACT).read_bytes(),(NATIVE/'releases/mac-launch-20261027/voice-selected-engine.json').read_bytes())
            self.assertEqual(yaml.safe_load((guest/i.BINDING).read_text()),r.binding_document(SELECTED))
            self.assertTrue((launch/'assembly-work/voice-component.json').is_file())

    def test_final_writer_refuses_different_model_or_image_selection(self):
        with tempfile.TemporaryDirectory() as td:
            launch,guest=self.fixture(Path(td));different=json.loads(json.dumps(PLAN));different['resolutions']['engine']['image']='ghcr.io/other/engine@sha256:'+'f'*64
            with patch.object(factory,'ROOT',launch),patch.object(factory,'PREP',launch/'preparation'),patch.object(factory,'native_module',side_effect=lambda name:i if name=='install.py' else r),patch.object(i,'install') as install,self.assertRaisesRegex(AssertionError,'selection differs'):
                factory.finalize_voice(different)
            install.assert_not_called();self.assertFalse((guest/i.CONTRACT).exists())

    def test_resolved_package_final_selection(self):
        with tempfile.TemporaryDirectory() as td:
            launch,guest=self.fixture(Path(td));selected=json.loads(json.dumps(SELECTED))
            selected['image']='ghcr.io/example/fake@sha256:'+'d'*64;selected['bindings']['transcriber-engine']=selected['image']
            plan=json.loads(json.dumps(PLAN));plan['resolutions']['engine']['image']=selected['image']
            (launch/'preparation/voice-selected-engine.json').write_text(json.dumps(selected,indent=2,sort_keys=True)+'\n')
            (guest/i.BINDING).write_text(yaml.safe_dump(r.binding_document(selected)))
            actual=i.install
            with patch.object(factory,'ROOT',launch),patch.object(factory,'PREP',launch/'preparation'),patch.object(factory,'native_module',side_effect=lambda name:i if name=='install.py' else r),patch.object(i,'load_reconciler',return_value=r),patch.object(i,'install',side_effect=lambda p:actual(p,guest,MagicMock())):
                factory.finalize_voice(plan)
            self.assertEqual(json.loads((guest/i.CONTRACT).read_text()),selected)

    def test_native_inputs_are_minimal_voice_overlay(self):
        pins=json.loads((HERE/'pins.json').read_text())
        self.assertEqual(pins['sourceInputs']['native']['commit'],pins['finalPins']['native'])
        self.assertEqual(pins['sourceInputs']['native']['ref'],'fix/local-voice-native-20261103')
        self.assertEqual(set(SELECTED['bindings']),{'transcriber','transcriber-engine'})

    def test_source_keeps_final_writer_after_last_binding_restore(self):
        # Source-order guard supplements (does not replace) the executable final
        # writer fixture above; no static assertion is counted as runtime proof.
        import inspect
        source=inspect.getsource(factory.finish)
        self.assertLess(source.index('writes=prepare(plan,managed)'),source.index('voice_receipt=finalize_voice(plan)'))
        self.assertIn("'voiceComponent':voice_receipt",source)

if __name__=='__main__':unittest.main()
