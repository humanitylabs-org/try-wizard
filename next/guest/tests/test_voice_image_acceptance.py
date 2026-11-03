"""Safe full acceptance capture and closed source-completion gate; no native work."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_voice_installer_diagnostic_result import undefined_globals, result_assignment

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'qa'
def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),QA/(name+'.py'))
    assert spec is not None and spec.loader is not None
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class Acceptance(unittest.TestCase):
    def setUp(self): self.guest=load('voice-image-acceptance');self.host=load('voice-image-acceptance-thales')
    def test_no_undefined_global_in_either_runner(self):
        for name in ('voice-image-acceptance','voice-image-acceptance-thales'):
            self.assertEqual(undefined_globals((QA/(name+'.py')).read_text()),set())
    def test_safe_nonzero_retained_before_raise(self):
        with self.assertRaisesRegex(RuntimeError,'safe installerCommands'):
            self.guest.installer_receipt([sys.executable,'-c',"import sys;sys.stderr.write(\"ModuleNotFoundError: No module named 'wam'\\nprivate-canary\\n\");sys.exit(3)"],ROOT,'apply')
        row=self.guest.REPORT['installerCommands']['apply']
        self.assertEqual(row['returncode'],3);self.assertFalse(row['timedOut'])
        self.assertIn("No module named 'wam'",row['stderr']['safeTail'])
        self.assertNotIn('private-canary',json.dumps(self.guest.REPORT))
        self.assertIn('update.py',self.guest.REPORT['sourceBindings'])
    def test_success_parse_does_not_publish_raw_stdout(self):
        row=self.guest.installer_receipt([sys.executable,'-c','print(\'{"alreadyInstalled": true}\')'],ROOT,'repeat')
        self.assertEqual(row,{'alreadyInstalled':True})
        evidence=self.guest.REPORT['installerCommands']['repeat']
        self.assertEqual(evidence['returncode'],0)
        self.assertNotIn('alreadyInstalled',evidence['stdout']['safeTail'])
    def test_timeout_still_persists_safe_evidence(self):
        def fail(*args,**kwargs): raise subprocess.TimeoutExpired('withheld',1,output=b'private-canary',stderr=b'ModuleNotFoundError: missing')
        with patch.object(self.guest.subprocess,'run',fail):
            with self.assertRaises(RuntimeError):self.guest.installer_receipt(['not-run'],ROOT,'rollback')
        self.assertTrue(self.guest.REPORT['installerCommands']['rollback']['timedOut'])
        self.assertNotIn('private-canary',json.dumps(self.guest.REPORT))
    def test_full_original_scope_and_stop_fences_retained(self):
        text=(QA/'voice-image-acceptance.py').read_text()
        for token in ('installer_receipt(',"'--apply'","'--rollback'",'for _ in range(3)',"'/api/voice/retry'",'lantern','window','normalRetryResponses','rollbackRetryInert',"'directStart'","'afterDaemonReload'",'selectedImagesAndSecurityPreserved'):
            self.assertIn(token,text)
        host=(QA/'voice-image-acceptance-thales.py').read_text()
        for token in ('source_binding(stage,a.source_completion_sha256)','m.admission()',"m.console_end(console,target,audit,'first',attempt)",'m.closed(disk)',"metadata(BASELINE)['inode']==27850082","metadata(BASELINE)['mode']==0o400",'productionStopVerified','ownedDiskDescriptorsClosed','baselineMetadataPreserved'):
            self.assertIn(token,host)
        self.assertLess(host.index('source_completion=source_binding'),host.index("subprocess.run(['/bin/cp','-c'"))
    def fixture(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);base=Path(tmp.name)
        root=base/'runtime';root.mkdir();admission=base/'runtime-admission';admission.mkdir()
        stage={'sourceStageSha256':'stage','sourceSpecSha256':'spec','newNativeSourceRevision':'new','focusedTestsExpected':31,'sourceSubmit':{'cwd':'synthetic','argv':['synthetic'],'timeout_seconds':1}}
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        log=admission/'native.log';log.write_text('synthetic evidence only')
        native_spec=admission/'native-spec.json';native_spec.write_text(json.dumps(dict(stage['sourceSubmit'],lane='light')))
        native=admission/'native.json';native.write_text(json.dumps({'job_id':'heavy_'+'0'*32,'state':'completed','exit_code':0,'log_sha256':sha(log),'spec_sha256':sha(native_spec)}))
        result=admission/'result.json';result.write_text(json.dumps({'success':True,'stageSha256':'stage','sourceRevision':'new','testsRun':31,'skipped':0,'failures':[],'errors':[]}))
        c={'parentVerifiedWorkerCompleted':True,'nativeExitCode':0,'jobId':'heavy_'+'0'*32,'sourceStageSha256':'stage','sourceSpecSha256':'spec','sourceRevision':'new'}
        for label,path in [('nativeReceipt',native),('nativeLog',log),('nativeSpec',native_spec),('sourceResult',result)]:c[label+'Path']=str(path);c[label+'Sha256']=sha(path)
        path=admission/'source-completion.json'
        def save():path.write_text(json.dumps(c));return sha(path)
        self.addCleanup(patch.stopall);patch.object(self.host,'HERE',root).start()
        return stage,c,path,save
    def test_missing_actual_completion_refused(self):
        stage,c,path,save=self.fixture()
        with self.assertRaises((OSError,RuntimeError)):self.host.source_binding(stage,None)
    def test_valid_synthetic_completion_checks_exact_identity(self):
        stage,c,path,save=self.fixture();self.assertEqual(self.host.source_binding(stage,save()),c)
    def test_wrong_spec_or_noncompleted_receipt_refused(self):
        stage,c,path,save=self.fixture();seal=save();stage['sourceSpecSha256']='wrong'
        with self.assertRaisesRegex(RuntimeError,'identity'):self.host.source_binding(stage,seal)
        stage['sourceSpecSha256']='spec';p=Path(c['nativeReceiptPath']);row=json.loads(p.read_text());row['state']='running';p.write_text(json.dumps(row));c['nativeReceiptSha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RuntimeError,'Native source'):self.host.source_binding(stage,save())
    def test_result_assignment_evaluates_after_real_binding_fixture(self):
        stage,c,path,save=self.fixture();source_completion=self.host.source_binding(stage,save())
        stage.update(sourceRevisions={},recoveryStageSha256='recovery',inheritedSourceStageSha256='inherited')
        # Exercise actual top-level result expression; no VM/archive/helper main.
        inventory=self.host.HERE/'derivative-inventory.json';inventory.write_text('{}')
        completion={'jobId':'synthetic-recovery','recoveryResultSha256':'result','nativeLogSha256':'log'}
        scope=dict(vars(self.host),stage=stage,a=SimpleNamespace(stage_sha256='s',recovery_completion_sha256='r',source_completion_sha256=save()),lease={},initial={},completion=completion,source_completion=source_completion,proof={'imageReceiptSha256':'synthetic-image-receipt'})
        exec(compile(result_assignment((QA/'voice-image-acceptance-thales.py').read_text()),'actual-result','exec'),scope)
        self.assertEqual(scope['result']['sourceJobId'],c['jobId']);self.assertFalse(scope['result']['success'])
        self.assertFalse(scope['result']['voiceTranscriptionAccepted'])
    def test_source_result_drift_refused(self):
        stage,c,path,save=self.fixture();seal=save();Path(c['sourceResultPath']).write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'drifted'):self.host.source_binding(stage,seal)

if __name__=='__main__':unittest.main(verbosity=2)
