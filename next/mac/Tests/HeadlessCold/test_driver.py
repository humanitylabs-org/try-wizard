#!/usr/bin/env python3
"""Cheap extraction/comparison contracts only; NEVER real-VM acceptance."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import build_driver
import run as runner
SOURCE=HERE.parents[3]

class DriverContracts(unittest.TestCase):
    def test_exact_extraction_and_desktop_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'generated'
            manifest=build_driver.generate(SOURCE,out)
            vm=(out/'VM.swift').read_text()
            self.assertIn('cachingMode: .cached, synchronizationMode: .full',vm)
            self.assertIn('init=/bin/sh wizard.dev=1 wizard.cold=',vm)
            self.assertIn('VZSharedDirectory(url: payload, readOnly: true)',vm)
            self.assertIn('func runGuestPatch',vm)
            joined='\n'.join(p.read_text() for p in out.glob('*.swift'))
            for desktop in ('NSWorkspace.shared','NSApplication.shared','NSApp.','caffeinate','launchctl','osascript'):
                self.assertNotIn(desktop,joined)
            self.assertNotIn('UserDefaults', (out/'Shared.swift').read_text())
            for name in ('WizardGuestActivation.swift','UpdateContract.swift','DiskIdentity.swift','GuestPatchCommand.swift'):
                original = SOURCE/('next/mac/App/' if name=='WizardGuestActivation.swift' else 'next/mac/Shared/')/name
                self.assertEqual((out/name).read_bytes(),original.read_bytes())
            for name,sha in manifest['generated'].items():
                self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),sha)
            self.assertIn('try WizardGuestActivation.snapshotStoppedDisk()', (out/'Admission.swift').read_text())

    def test_fail_closed_production_drift(self):
        # Resolve a real source mismatch without compiling or exercising any VM.
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch
            with patch.object(build_driver.subprocess,'check_output',return_value=b'not pinned source'):
                with self.assertRaisesRegex(RuntimeError,'Production source drift'):
                    build_driver.generate(SOURCE,Path(tmp)/'generated')

    def test_preservation_comparator_rejects_loss(self):
        spec=importlib.util.spec_from_file_location('preservation',SOURCE/'next/guest/stack-preservation.py')
        assert spec is not None and spec.loader is not None
        guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
        before={'protected':{'file':'hash'},'installedApps':['hermes-agent'],'accountFiles':{},
            'configNormalizedSHA256':'config','configRawSHA256':'old','configExpectedSHA256':'new',
            'authSnapshot':guard.auth_snapshot(None),
            'databases':{'state.db':{'messages':{'columns':['id'],'rows':['message-hash']},
                                     'sessions':{'columns':['id'],'rows':['session-hash']}}}}
        after=copy.deepcopy(before);after['configRawSHA256']='new'
        self.assertTrue(runner.compare(before,after,guard)['existingRowsPreserved'])
        for key in ('protected','installedApps','configRawSHA256'):
            bad=copy.deepcopy(after);bad[key]={} if isinstance(bad[key],dict) else 'wrong'
            with self.assertRaises(AssertionError):runner.compare(before,bad,guard)
        bad=copy.deepcopy(after);bad['databases']['state.db']['messages']['rows']=[]
        with self.assertRaises(AssertionError):runner.compare(before,bad,guard)
        with self.assertRaises(AssertionError):runner.compare(before,after,guard,rollback=True)

    def test_failure_cannot_be_reported_as_acceptance(self):
        source=(HERE/'run.py').read_text()
        self.assertIn("assert rc==0 and result['success'] and result['stopped']",source)
        self.assertIn("assert report['success'] and report['cleanupVerified']",source)
        self.assertIn("assert len(events)<256",(HERE/'guest_audit.py').read_text())
        self.assertNotIn('wizard_heavy_submit', source.replace('Durable-worker-only',''))

if __name__=='__main__':unittest.main()
