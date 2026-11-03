"""Tiny network/VM-free regressions for the diagnostic, not product acceptance."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'qa/voice-installer-diagnostic.py'
spec=importlib.util.spec_from_file_location('diagnostic',SOURCE)
assert spec is not None and spec.loader is not None
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class DiagnosticTests(unittest.TestCase):
    def test_nonzero_not_discarded(self):
        # Exercise a real short subprocess: no mocks for stream/exit semantics.
        row=m.observe_installer([sys.executable,'-c',"import sys;print('synthetic-only');sys.stderr.write(\"ModuleNotFoundError: No module named 'wam'\\n\");sys.exit(7)"],{})
        self.assertEqual(row['returncode'],7)
        self.assertIn("No module named 'wam'",row['stderr']['safeTail'])
        self.assertFalse(row['stderr']['rawExported'])
        self.assertEqual(row['stdout']['sha256'],hashlib.sha256(b'synthetic-only\n').hexdigest())

    def test_raw_bytes_and_redaction(self):
        row=m.stream_evidence(b'\xffsecret-canary\nAuthorization: Bearer secret-canary\n',{})
        self.assertEqual(row['bytes'],len(b'\xffsecret-canary\nAuthorization: Bearer secret-canary\n'))
        self.assertNotIn('secret-canary',json.dumps(row))
        self.assertEqual(row['sha256'],hashlib.sha256(b'\xffsecret-canary\nAuthorization: Bearer secret-canary\n').hexdigest())

    def test_source_bound_frames(self):
        p='/owned/overlay/opt/wizard/voice/update.py'
        trusted={p:{'label':'update.py','lines':129,'functions':{'apply','lifecycle'}}}
        raw='  File "'+p+'", line 78, in apply\n  File "'+p+'", line 15, in lifecycle\n'
        row=m.stream_evidence(raw,trusted)
        self.assertEqual(row['trustedFrames'][-1],{'file':'update.py','function':'lifecycle','line':15})

    def test_forged_frame_rejected(self):
        trusted={'/owned/update.py':{'label':'update.py','lines':10,'functions':{'apply'}}}
        for raw in ('  File "/secret/update.py", line 2, in apply',
                    '  File "/owned/update.py", line 11, in apply',
                    '  File "/owned/update.py", line 2, in stolen'):
            self.assertEqual(m.stream_evidence(raw,trusted)['trustedFrames'],[])
            self.assertNotIn('/secret/',json.dumps(m.stream_evidence(raw,trusted)))

    def test_unknown_exception_payload_withheld(self):
        row=m.stream_evidence('RuntimeError: token=secret-canary\nCalledProcessError: private argv secret-canary',{})
        self.assertNotIn('secret-canary',json.dumps(row))
        self.assertIn('RuntimeError: <payload withheld>',row['safeTail'])

    def test_source_literal_allowlist(self):
        d=Path(__file__).resolve().parents[1]
        # Actual product input, no source substitutions or synthetic acceptance.
        trusted=m.trusted_sources(d)
        self.assertIn('RuntimeError: Unknown voice rollback fence; review before updating',trusted['__literal_errors__'])
        self.assertEqual(trusted[str(d/'overlay/opt/wizard/voice/install.py')]['sha256'],hashlib.sha256((d/'overlay/opt/wizard/voice/install.py').read_bytes()).hexdigest())

    def test_tail_bounded(self):
        row=m.stream_evidence(('sensitive-canary\n'*3000),{})
        self.assertLessEqual(len(row['safeTail']),m.MAX_VISIBLE)
        self.assertTrue(row['tailTruncated'])
        self.assertNotIn('sensitive-canary',json.dumps(row))

    def test_timeout_partial_stream_preserved(self):
        def timeout(*args,**kwargs):raise subprocess.TimeoutExpired('withheld',9,output=b'partial',stderr=b'PermissionError: private')
        row=m.observe_installer(['not-run'],{},invoke=timeout)
        self.assertTrue(row['timedOut']);self.assertIsNone(row['returncode'])
        self.assertEqual(row['stdout']['sha256'],hashlib.sha256(b'partial').hexdigest())
        self.assertIn('PermissionError',row['stderr']['safeTail'])

    def test_wam_probe_exact_route_no_config(self):
        def invoke(argv,**kwargs):
            self.assertEqual(argv[:7],['sudo','-u','wizard','env','HOME=/home/wizard','python3','-c'])
            self.assertNotIn('Config()',argv[-1]);self.assertNotIn("sys.path.insert",argv[-1])
            return subprocess.CompletedProcess(argv,0,b'{"uid":1000,"wamDiscoverable":false,"sourcePackageExists":true}',b'')
        row=m.wam_preconditions(invoke)
        self.assertTrue(row['valid']);self.assertFalse(row['fields']['wamDiscoverable'])

    def test_invalid_probe_fields_withheld(self):
        def invoke(argv,**kwargs):return subprocess.CompletedProcess(argv,0,b'{"token":"secret-canary"}',b'')
        row=m.wam_preconditions(invoke)
        self.assertFalse(row['valid']);self.assertNotIn('secret-canary',json.dumps(row))

    def test_native_runner_keeps_fences_and_cannot_accept(self):
        path=SOURCE.with_name('voice-installer-diagnostic-thales.py')
        text=path.read_text();tree=ast.parse(text)
        self.assertIn("m.admission()",text)
        self.assertIn("subprocess.run(['/bin/cp','-c',str(BASELINE)",text)
        self.assertIn("metadata(BASELINE)['inode']==27850082",text)
        self.assertIn("metadata(BASELINE)['mode']==0o400",text)
        self.assertIn("m.console_end(console,target,audit,'first',attempt)",text)
        self.assertIn("'Actual successful native recovery receipt required'",text)
        self.assertIn("'Missing clean production stop/descriptor proof'",text)
        self.assertIn("m.closed(disk);result['ownedDiskDescriptorsClosed']=True",text)
        self.assertNotIn('success=True',text)
        self.assertNotIn('/usr/bin/say',text)
        self.assertNotIn("'docker', 'load'",text)
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        self.assertTrue(any(isinstance(n,ast.Raise) and isinstance(n.exc,ast.Call) and isinstance(n.exc.func,ast.Name) and n.exc.func.id=='RuntimeError' for n in ast.walk(main)))

    def test_diagnostic_cannot_continue_acceptance(self):
        tree=ast.parse(SOURCE.read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        src=ast.get_source_segment(SOURCE.read_text(),main)
        assert src is not None
        self.assertEqual(src.count('observe_installer('),1)
        for forbidden in ('/api/voice/retry','--rollback','syntheticTranscription','alreadyInstalled'):
            self.assertNotIn(forbidden,src)
        self.assertIsInstance(main.body[-1],ast.Raise)
        self.assertIn('raise SystemExit(1)',SOURCE.read_text())
        self.assertIn('success=False,fullAcceptance=False,voiceTranscriptionAccepted=False',SOURCE.read_text())

if __name__=='__main__':unittest.main(verbosity=2)
