"""Selected-image transactions with fake systemd/WAM/Docker, no runtime claims."""
import hashlib,json,tempfile,types,unittest,shutil
from pathlib import Path
from unittest.mock import MagicMock,patch
from test_voice_recovery import i,r,ROOT,load
u=load('voice_update_tests',ROOT/'overlay/opt/wizard/voice/update.py')

class Update(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.root=self.base/'guest';self.root.mkdir();self.payload=self.base/'payload';self.payload.mkdir()
        for rel in i.FILES:
            target=self.payload/'overlay'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'overlay'/rel,target)
            target=self.root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('old '+rel)
        self.old=json.loads((ROOT/'releases/mac-launch-20261027/voice-selected-engine.json').read_text());self.new=json.loads(json.dumps(self.old))
        # Explicit synthetic image for fakes only, never a packaging output.
        self.new['image']='ghcr.io/example/fake@sha256:'+'c'*64;self.new['bindings']['transcriber-engine']=self.new['image']
        self.binding=self.root/i.BINDING;self.binding.parent.mkdir(parents=True);self.binding.write_text(__import__('yaml').safe_dump(r.binding_document(self.old)))
        (self.payload/'selected-engine.json').write_text(json.dumps(self.new));(self.payload/'voice-engine.oci.tar').write_bytes(b'fake transport only')
        self.d={'schema':1,'previousSelection':self.old,'selection':self.new,'archive':'voice-engine.oci.tar','archiveSha256':u.sha(self.payload/'voice-engine.oci.tar'),'imageId':'fake-id','securityPassed':True,'configPreserved':True,'baseLayersPreserved':True}
        self.descriptor=self.payload/'voice-package.json';self.descriptor.write_text(json.dumps(self.d));self.calls=[]
        def run(argv,**kw):
            self.calls.append(argv)
            if argv[:3]==['docker','image','inspect']:
                return types.SimpleNamespace(stdout=json.dumps([{'Id':'fake-id','RepoDigests':[argv[3]],'Architecture':'arm64'}]))
            return types.SimpleNamespace(stdout='',returncode=0)
        self.execute=run
    def apply(self):return u.apply(self.payload,i,self.root,self.execute)
    def test_apply_and_repeat(self):
        self.assertTrue(self.apply()['selectedImageUpdated']);self.assertTrue(self.apply()['alreadyInstalled'])
        self.assertEqual(sum(c[:2]==['docker','load'] for c in self.calls),1)
        self.assertEqual(__import__('yaml').safe_load(self.binding.read_text()),r.binding_document(self.new))
    def test_rollback_and_subsequent_retry(self):
        old=self.binding.read_bytes();self.apply();self.assertTrue(u.recover(self.payload,i,self.root,self.execute)['coordinatorFenced'])
        self.assertEqual(self.binding.read_bytes(),old);self.assertEqual((self.root/i.FENCE).read_bytes(),i.FENCE_BYTES)
        self.assertFalse((self.root/i.CONTRACT).exists());self.assertTrue(self.apply()['selectedImageUpdated'])
    def test_corrupt_archive_before_lifecycle(self):
        (self.payload/'voice-engine.oci.tar').write_bytes(b'corrupt')
        with self.assertRaises(AssertionError):self.apply()
        self.assertEqual(self.calls,[])
    def test_foreign_binding_before_lifecycle(self):
        self.binding.write_text('services: {transcriber-engine: {privileged: true}}')
        with self.assertRaises(r.Refusal):self.apply()
        self.assertEqual(self.calls,[])
    def test_interrupted_journal_refused(self):
        (self.root/u.STATE).mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError,'Interrupted'):self.apply()
        self.assertEqual(self.calls,[])
    def test_failure_restores_and_fences(self):
        original=self.binding.read_bytes();real=self.execute
        def fail(argv,**kw):
            if argv[:2]==['docker','load']:raise RuntimeError('injected')
            return real(argv,**kw)
        self.execute=fail
        with self.assertRaisesRegex(RuntimeError,'injected'):self.apply()
        self.assertEqual(self.binding.read_bytes(),original);self.assertEqual((self.root/i.FENCE).read_bytes(),i.FENCE_BYTES)
    def test_approval_marker_refused(self):
        p=self.root/'var/lib/wizard/voice-rollback-approved';p.parent.mkdir(parents=True);p.touch()
        with self.assertRaisesRegex(RuntimeError,'marker'):self.apply()
        self.assertEqual(self.calls,[])
    def test_unknown_fence_refused(self):
        p=self.root/i.FENCE;p.parent.mkdir(parents=True);p.write_text('foreign')
        with self.assertRaisesRegex(RuntimeError,'fence'):self.apply()
        self.assertEqual(self.calls,[])
    def test_rollback_fence_precedes_restored_bytes(self):
        self.apply();events=[];real=i.os.replace
        def replace(src,dst):
            if '.restore.' in str(src):
                self.assertEqual((self.root/i.FENCE).read_bytes(),i.FENCE_BYTES)
                events.append(str(dst))
            return real(src,dst)
        with patch.object(i.os,'replace',side_effect=replace):u.recover(self.payload,i,self.root,self.execute)
        self.assertTrue(events);self.assertIn(['systemctl','reset-failed','wizard-voice'],self.calls)

if __name__=='__main__':unittest.main()
