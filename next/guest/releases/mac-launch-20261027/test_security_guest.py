#!/usr/bin/env python3
"""Guest readiness, isolated trust proof and failure evidence regressions."""
import copy, importlib.util, json, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('closure',HERE/'security-closure.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def row(restarting=False,restarts=0,started='start',health='healthy'):
    return {'Id':'cid','Image':'sha256:test','RestartCount':restarts,'State':{
        'Running':not restarting,'Restarting':restarting,'StartedAt':started,'Health':{'Status':health}}}


class GuestSecurity(unittest.TestCase):
    def test_waits_through_restart_and_requires_continuous_stability(self):
        clock=[0]
        states=iter([row(True),row(),row(restarts=1,started='new'),row(restarts=1,started='new'),row(restarts=1,started='new')])
        with patch.object(m,'inspect_container',side_effect=lambda *_:next(states)),patch.object(m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(m.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
            final=m.wait_stable('docker','cid',timeout=12,stable_seconds=4)
        self.assertEqual(final['RestartCount'],1)
        self.assertEqual(clock[0],8)

    def test_restart_loop_and_unhealthy_container_have_bounded_deadline(self):
        for state in [row(True),row(health='unhealthy')]:
            clock=[0]
            with patch.object(m,'inspect_container',return_value=state),patch.object(m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(m.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
                with self.assertRaises(TimeoutError):m.wait_stable('docker','cid',timeout=6,stable_seconds=4)
            self.assertEqual(clock[0],6)

    def test_network_exemption_requires_every_attached_network_internal(self):
        r={'NetworkSettings':{'Networks':{'one':{},'two':{}}}}
        with patch.object(m,'run',return_value=json.dumps([{'Internal':True},{'Internal':False}])):self.assertFalse(m.internal_only('docker',r))
        with patch.object(m,'run',return_value=json.dumps([{'Internal':True},{'Internal':True}])):self.assertTrue(m.internal_only('docker',r))
        self.assertFalse(m.internal_only('docker',{'NetworkSettings':{'Networks':{}}}))

    def test_offline_proof_requires_exact_running_trust_inputs(self):
        reference={'contexts':{'system':['good']},'trustFiles':{'/etc/ssl/cert.pem':'hash'},'runtimes':{'curl':'hash'},'rejectedAdvisoryRoots':['a','b','c','d'],'environment':{}}
        m.compare_internal(reference,copy.deepcopy(reference))
        for field in reference:
            altered=copy.deepcopy(reference);altered[field]={'drift':True}
            with self.assertRaises(AssertionError):m.compare_internal(reference,altered)

    def test_missing_or_unproved_internal_image_is_not_network_pass(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'preparation').mkdir();p=root/'preparation/security-image-plan.json'
            p.write_text(json.dumps({'resolutions':{}}))
            (root/'security-preflight.json').write_text(json.dumps({'passed':True,'allGuestImagesEnumerated':True,'planSha256':m.sha(p),'resolutions':{}}))
            with self.assertRaisesRegex(AssertionError,'no exact online-tested'):m.internal_image_proof(root,'sha256:unknown')

    def test_dns_failure_stays_failed_and_captures_logs_and_state(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);state=row()
            def proc(argv,**kw):
                if argv[1]=='exec':return subprocess.CompletedProcess(argv,6,'','Could not resolve host example.com')
                return subprocess.CompletedProcess(argv,0,'state or log','')
            with patch.object(m,'wait_stable',return_value=state),patch.object(m,'internal_only',return_value=False),patch.object(m,'inspect_container',return_value=state),patch.object(m.subprocess,'run',side_effect=proc):
                result=m.check_guest('docker',root,'cid','sha256:test',{})
            self.assertEqual(result['returncode'],6)
            self.assertIn('not certificate rejection',result['log'])
            for name in ['state','logs']:
                file=root/result['diagnostics'][name];self.assertTrue(file.is_file());self.assertEqual(file.stat().st_mode&0o777,0o600)

    def test_readiness_timeout_captures_diagnostics_without_exec(self):
        with tempfile.TemporaryDirectory() as t,patch.object(m,'wait_stable',side_effect=TimeoutError('restart loop')),patch.object(m,'capture_failure',return_value={'logs':'logs','state':'state'}) as capture:
            result=m.check_guest('docker',Path(t),'cid','sha256:test',{})
            self.assertEqual(result['returncode'],124);capture.assert_called_once()

    def test_restart_during_successful_tls_check_is_failure(self):
        with tempfile.TemporaryDirectory() as t,patch.object(m,'wait_stable',return_value=row()),patch.object(m,'internal_only',return_value=False),patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'TLS pass','')),patch.object(m,'inspect_container',return_value=row(restarts=1)),patch.object(m,'capture_failure',return_value={}):
            result=m.check_guest('docker',Path(t),'cid','sha256:test',{})
            self.assertEqual(result['returncode'],1);self.assertIn('restarted',result['log'])

if __name__=='__main__':unittest.main()
