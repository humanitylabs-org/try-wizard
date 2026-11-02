#!/usr/bin/env python3
"""Control-plane admission contracts: generated fixtures are UNIT TESTS, not acceptance receipts."""
import copy, hashlib, importlib.util, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('launch_audit',ROOT/'audit.py');assert spec and spec.loader
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class AdmissionTests(unittest.TestCase):
    def setUp(self):self.manifest=json.loads((ROOT/'pins.json').read_text())
    def test_actual_inputs_block_without_build(self):
        proc=subprocess.run([sys.executable,str(ROOT/'audit.py')],capture_output=True,text=True)
        self.assertEqual(proc.returncode,2);receipt=json.loads(proc.stdout)
        self.assertFalse(receipt['buildStarted']);self.assertFalse(receipt['publishing'])
        self.assertTrue(any(e.startswith('IMAGE_DIGESTS_PENDING') for e in receipt['blockers']))
        self.assertTrue(any(e.startswith('SOURCE_VERIFICATION_V5') for e in receipt['blockers']))
        self.assertTrue(any(e.startswith('SECURITY_IMAGE_CLOSURE') for e in receipt['blockers']))
    def test_queue_count_rejected(self):
        m=copy.deepcopy(self.manifest);m['queue']['entryCount']+=1
        self.assertIn('queue coverage count mismatch',audit.inspect(m,None))
    def test_stable_bytes_immutable(self):
        m=copy.deepcopy(self.manifest);m['stable']['sha256']='0'*64
        self.assertIn('stable release snapshot digest mismatch',audit.inspect(m,None))
    def test_native_main_not_accepted(self):
        m=copy.deepcopy(self.manifest);m['finalPins']['native']='main'
        self.assertIn('unresolved final pin: native',audit.inspect(m,None))
    def test_adapter_is_hash_pinned_not_bare_factory_build(self):
        e=self.manifest['execution'];self.assertEqual(e['recipe'],'preparation/assemble.py')
        self.assertEqual(e['sha256'],hashlib.sha256((ROOT/'assemble.py').read_bytes()).hexdigest())
        self.assertNotIn('build-image.sh',json.dumps(e));self.assertIn('--execute',e['argv'])
    def test_absent_recipe_rejected(self):
        m=copy.deepcopy(self.manifest);m['execution']=None
        self.assertIn('reviewed complete assembly recipe is not pinned',audit.inspect(m,None))
    def test_exact_source_shas(self):
        for value in self.manifest['sourceInputs'].values():self.assertRegex(value['commit'],r'^[0-9a-f]{40}$')
    def test_retained_base_and_boot_are_immutable(self):
        base=self.manifest['assembly']['base'];self.assertRegex(base['sha256'],r'^[0-9a-f]{64}$')
        self.assertEqual(base['sha256'],'64ddc2b8123b3185668aab666cd93843a228d769a2ab55c68e64e00a4c1f1366')
        self.assertEqual(set(base['boot']),{'vmlinux','initrd'})
    def test_plan_has_full_assembly_without_executing(self):
        proc=subprocess.run([sys.executable,str(ROOT/'assemble.py'),'--stage-root','.'],capture_output=True,text=True,check=True)
        plan=json.loads(proc.stdout);self.assertFalse(plan['publishing']);self.assertEqual(plan['signing'],'unsigned/pluggable')
        for key in ['WIZARD_RELEASE-install-without-WAM_REF','security-all-client-closure','offline-fsck-shrink-and-zero-free-blocks','BOM-manifest-sparse-archive']:self.assertIn(key,plan['steps'])
    def test_installer_pinned_and_no_developer_override(self):
        text=(ROOT/'guest-apply.py').read_text()
        self.assertIn("assert sha(installer)==pins['osInstaller']['sha256']",text)
        self.assertIn("WIZARD_RELEASE_BASE='file://'+str(release_dir)",text)
        self.assertIn("WIZARD_STRICT='1'",text)
        self.assertIn("k not in ['WAM_REF'",text)
    def test_three_packaging_jobs_do_not_publish_tags(self):
        text=(ROOT/'package-image.py').read_text()
        self.assertIn('push-by-digest=true',text);self.assertNotIn("'--push'",text)
        self.assertIn('DOCKER_CONFIG',text);self.assertNotIn('credsStore',text)
    def test_v5_is_linux_short_temp_and_runs_full_suites(self):
        text=(ROOT/'verify-sources-v5.py').read_text()
        for token in ['TMPDIR=/work/t','chmod 1777','npx vitest run','python3 tests/managed_recovery_test.py','node --test tests/*.test.mjs','python -m pytest -q -rs']:self.assertIn(token,text)
    def test_security_not_declared_complete(self):
        plan=json.loads((ROOT/'security-image-plan.json').read_text());self.assertFalse(plan['complete'])
        self.assertEqual(plan['mandatoryQueueId'],81)
    def test_security_does_not_count_dns_failure_as_tls_rejection(self):
        text=(ROOT/'security-closure.py').read_text()
        self.assertIn('test "$rc" = 60',text);self.assertIn('SSLCertVerificationError',text)
        self.assertIn('https://example.com/',text);self.assertIn('certifi/cacert.pem',text)
        self.assertIn("v[1]<23",text)
    def test_direct_execution_cannot_bypass_admission(self):
        text=(ROOT/'assemble.py').read_text()
        self.assertLess(text.index('errors=audit.inspect(pins,root)'),text.index("work=root/'assembly-work'"))
    def test_resolver_does_not_launder_changed_sources(self):
        text=(ROOT/'resolve-images.py').read_text();self.assertIn('immutable staged input changed',text)
        self.assertIn("row['pullVerified'] is True",text);self.assertIn("security['passed'] is True",text)

    def staged_fixture(self,root,prep):
        import shutil
        for f in ROOT.iterdir():
            if f.is_file():shutil.copy2(f,prep/f.name)
        m=copy.deepcopy(self.manifest)
        for key in ['wam','service','ux']:
            m['assembly']['images'][key]['digest']='sha256:'+('a' if key=='wam' else 'b' if key=='service' else 'c')*64
        def emit(path,value):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
        for key,pin in m['finalPins'].items():emit(root/'final'/key/'.wizard-source.json',{'commit':pin})
        provision=root/'final/native/next/guest/overlay/opt/wizard/bin/wizard-provision';provision.parent.mkdir(parents=True);provision.write_text('env -u WAM_REF WIZARD_RELEASE=fixture')
        installer=root/'final/wam/get.sh';installer.write_text('unit fixture, not executable acceptance')
        m['osInstaller']['sha256']=hashlib.sha256(installer.read_bytes()).hexdigest()
        for rel in ['server/service.mjs','server/hermes-http-readers.mjs','server/read-human-sessions.py']:
            target=root/'final/service'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text("['cli', 'tui']")
            m['service64Proof'][rel]=hashlib.sha256(target.read_bytes()).hexdigest()
        for key in ['wam','service','ux']:
            emit(root/'image-packaging'/key/'result.json',{'sourceCommit':m['finalPins'][key],'pullVerified':True,**m['assembly']['images'][key]})
        emit(root/'source-checks-v5/result.json',{'version':5,'passed':True,'finalPins':m['finalPins'],'commands':[{'key':k,'returncode':0} for k in ['linux-create','linux-full','linux-logs','factory-pins','phone','stock-builder','factory-admission']]})
        image='unit.invalid/test@sha256:'+'f'*64
        emit(prep/'security-image-plan.json',{'complete':True,'images':[image]})
        emit(root/'security-preflight.json',{'passed':True,'allGuestImagesEnumerated':True,'images':[image],'checks':[{'target':image,'returncode':0}]})
        emit(root/'evidence/ux-final-ci.json',{'headSha':m['finalPins']['ux'],'conclusion':'success'})
        recipe=root/'preparation/assemble.py';recipe.parent.mkdir(exist_ok=True);recipe.write_bytes((ROOT/'assemble.py').read_bytes())
        m['execution']['sha256']=hashlib.sha256(recipe.read_bytes()).hexdigest()
        for rel in m['execution'].get('inputs',{}):
            target=root/rel;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/rel.removeprefix('preparation/')).read_bytes())
        base=root/'unit-base-not-a-VM';base.write_bytes(b'unit fixture')
        m['assembly']['base']['path']=str(base)
        emit(root/'staged-files.json',{'files':{},'symlinks':{}})
        rc=json.loads((prep/'wizard-os-release-candidate.json').read_text());rc['status']='factory-bootstrap-ready'
        emit(prep/'wizard-os-release-candidate.json',rc);m['wizardOsCandidate']['sha256']=hashlib.sha256((prep/'wizard-os-release-candidate.json').read_bytes()).hexdigest()
        return m

    def test_staged_gate_requires_all_three_axes_and_real_receipt_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'stage';root.mkdir();prep=Path(temp)/'prep';prep.mkdir()
            m=self.staged_fixture(root,prep)
            with patch.object(audit,'HERE',prep):
                self.assertEqual(audit.inspect(m,root),[])
                for rel,change,prefix in [
                    ('source-checks-v5/result.json',lambda d:d.update(passed=False),'SOURCE_VERIFICATION_V5'),
                    ('security-preflight.json',lambda d:d.update(passed=False),'SECURITY_IMAGE_CLOSURE'),
                    ('evidence/ux-final-ci.json',lambda d:d.update(headSha='0'*40),'UX_FINAL_HEAD_CI'),
                    ('image-packaging/service/result.json',lambda d:d.update(pullVerified=False),'IMAGE_DIGESTS_PENDING')]:
                    p=root/rel;before=p.read_bytes();d=json.loads(before);change(d);p.write_text(json.dumps(d))
                    self.assertTrue(any(e.startswith(prefix) for e in audit.inspect(m,root)),rel);p.write_bytes(before)
                companion=root/'preparation/post-setup-apps.py';before=companion.read_bytes();companion.write_text('changed')
                self.assertTrue(any(e.startswith('factory recipe input missing or digest mismatch') for e in audit.inspect(m,root)))
                companion.write_bytes(before)
                malicious=copy.deepcopy(m);malicious['execution']['argv']=['bash','build-image.sh']
                self.assertIn('reviewed complete assembly recipe is not pinned',audit.inspect(malicious,root))
                allowlist=root/'final/service/server/read-human-sessions.py';allowlist.write_text('missing imported CLI/TUI')
                self.assertTrue(any(e.startswith('SERVICE_64_ALLOWLISTS') for e in audit.inspect(m,root)))

if __name__=='__main__':unittest.main()
