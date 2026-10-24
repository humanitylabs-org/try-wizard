#!/usr/bin/env python3
"""Light control-plane contract tests. No Docker, VM, install or publish."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    assert spec is not None and spec.loader is not None
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

audit=module('audit','audit.py')
freeze=module('freeze','freeze-release.py')

class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.pins=json.loads((HERE/'pins.json').read_text())
        self.queue=json.loads((HERE/'queue-inventory.json').read_text())

    def check_changed(self,file,edit):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for f in ['queue-mapping.json','wizard-os-release-candidate.json','wizard-os-current-stable.json']:
                shutil.copy2(HERE/f,root/f)
            obj=json.loads((root/file).read_text());edit(obj)
            (root/file).write_text(json.dumps(obj))
            pins=copy.deepcopy(self.pins)
            spec=pins['queue']['mapping'] if file=='queue-mapping.json' else pins['wizardOsCandidate']
            spec['sha256']=hashlib.sha256((root/file).read_bytes()).hexdigest()
            with patch.object(audit,'HERE',root):return audit.inspect_preparation(pins,self.queue)

    def test_full_mapping_preserves_exact_original_rows(self):
        m=json.loads((HERE/'queue-mapping.json').read_text())
        self.assertEqual(len(m['entries']),84)
        self.assertEqual([r['id'] for r in m['entries']],list(range(1,85)))
        self.assertEqual([(r['entry'],r['queueLine']) for r in m['entries']],[(r['entry'],r['queueLine']) for r in self.queue['entries']])
        self.assertEqual(sum(m['counts'].values()),84)
        self.assertTrue(all(r['acceptance']=='not-run-on-final-guest' for r in m['entries']))

    def test_duplicate_mapping_id_is_rejected(self):
        self.assertIn('queue mapping IDs must be complete, ordered and unique',self.check_changed('queue-mapping.json',lambda m:m['entries'][1].update(id=1)))

    def test_changed_queue_text_is_rejected(self):
        self.assertIn('queue mapping altered original queue entries',self.check_changed('queue-mapping.json',lambda m:m['entries'][0].update(entry='not the original')))

    def test_different_component_pin_is_rejected(self):
        self.assertIn('queue mapping component pin mismatch: 1',self.check_changed('queue-mapping.json',lambda m:m['entries'][0]['components'][0].update(pinnedCommit='0'*40)))

    def test_stale_selection_rejected(self):
        self.assertIn('queue mapping selects different final pins',self.check_changed('queue-mapping.json',lambda m:m.update(sourceSelectionSha256='0'*64)))

    def test_candidate_different_service_source_rejected(self):
        self.assertIn('candidate component pin mismatch: service',self.check_changed('wizard-os-release-candidate.json',lambda m:m['components']['wizard-agent-service'].update(commit='0'*40)))

    def test_source_rc_not_admitted_as_bootstrap(self):
        errors=audit.inspect_preparation(self.pins,self.queue)
        self.assertIn('Wizard OS source RC is not yet an executable factory bootstrap release',errors)
        self.assertIn('queue has explicitly uncarried or unproven requirements; see queue-mapping.json',errors)
        self.assertFalse(any('digest mismatch' in e for e in errors))

    def test_freeze_does_not_relabel_stable_images(self):
        raw=(HERE/'wizard-os-current-stable.json').read_bytes();stable=json.loads(raw)
        rc=freeze.freeze(self.pins,stable,raw,{})
        self.assertNotIn('images',rc)
        self.assertEqual(rc['bootstrapImages'],stable['images'])
        self.assertIsNone(rc['candidateImagePolicy']['wizard-agent-service']['digest'])
        self.assertEqual(rc['components']['wizard-ux']['commit'],self.pins['finalPins']['ux'])
        self.assertEqual(rc['default_apps']['recorder']['image'],self.pins['recorderImage']['arm64Image'])
        self.assertFalse(rc['promote']);self.assertFalse(rc['publish'])

if __name__=='__main__':unittest.main()
