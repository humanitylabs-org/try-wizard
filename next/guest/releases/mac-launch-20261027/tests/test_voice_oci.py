"""Tiny fabricated OCI archives exercise real derivation; NOT real image proof."""
import hashlib,io,json,sys,tarfile,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import voice_oci as v

class OCI(unittest.TestCase):
    def fixture(self,extra=None):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
        old=b'old fake module';self.pin=hashlib.sha256(old).hexdigest();self.name='app/speaches/executors/parakeet.py'
        layer=io.BytesIO()
        with tarfile.open(fileobj=layer,mode='w') as t:
            v.add(t,self.name,old);v.add(t,'app/speaches/executors/__pycache__/parakeet.cpython-312.pyc',b'stale fake bytecode')
            if extra:
                info=tarfile.TarInfo('app/speaches');info.type=tarfile.SYMTYPE;info.linkname='/elsewhere';t.addfile(info)
        raw=layer.getvalue();ld=v.digest(raw)
        self.cfg={'architecture':'arm64','os':'linux','config':{'User':'ubuntu','Entrypoint':['uvicorn'],'Env':['KEEP=1'],'Volumes':{'/cache':{}}},'rootfs':{'type':'layers','diff_ids':[ld]},'history':[{'created_by':'old fixture'}]}
        cb=v.encoded(self.cfg);cd=v.digest(cb);self.layers=[{'mediaType':'application/vnd.oci.image.layer.v1.tar','digest':ld,'size':len(raw)}]
        manifest={'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json','config':{'mediaType':'application/vnd.oci.image.config.v1+json','digest':cd,'size':len(cb)},'layers':self.layers};mb=v.encoded(manifest);md=v.digest(mb)
        index={'schemaVersion':2,'manifests':[{'mediaType':'application/vnd.oci.image.manifest.v1+json','digest':md,'size':len(mb),'annotations':{'org.opencontainers.image.ref.name':'fake'}}]}
        self.base=self.root/'base.tar';self.out=self.root/'new.tar'
        with tarfile.open(self.base,'w') as t:
            for name,data in [('oci-layout',v.encoded({'imageLayoutVersion':'1.0.0'})),(v.blob_path(ld),raw),(v.blob_path(cd),cb),(v.blob_path(md),mb),('index.json',v.encoded(index))]:v.add(t,name,data)
    def test_real_append_and_bytecode_whiteout(self):
        self.fixture();before=v.oci.sha(self.base);new,d=v.derive(self.base,self.out,b'new fake module',self.pin,'ghcr.io/example/fake')
        self.assertEqual(new['config']['config'],self.cfg['config']);self.assertEqual(v.oci.sha(self.base),before)
        with tarfile.open(self.out) as t:
            index=json.load(t.extractfile('index.json'));annotations=index['manifests'][0]['annotations']
            self.assertEqual(annotations['io.containerd.image.name'],'ghcr.io/example/fake@'+new['digest'])
            self.assertNotIn('org.opencontainers.image.ref.name',annotations)
            manifest=json.load(t.extractfile(v.blob_path(new['manifestDigest'])))
            self.assertEqual(manifest['layers'][:-1],self.layers)
            with tarfile.open(fileobj=t.extractfile(v.blob_path(d['newLayerDigest']))) as layer:
                self.assertEqual(layer.extractfile(self.name).read(),b'new fake module')
                self.assertIn('app/speaches/executors/__pycache__/.wh.parakeet.cpython-312.pyc',layer.getnames())
    def test_wrong_predecessor_refused(self):
        self.fixture()
        with self.assertRaises(AssertionError):v.derive(self.base,self.out,b'new', '0'*64,'ghcr.io/example/fake')
        self.assertFalse(self.out.exists())
    def test_parent_redirection_refused(self):
        self.fixture(extra=True)
        with self.assertRaises(AssertionError):v.derive(self.base,self.out,b'new',self.pin,'ghcr.io/example/fake')
    def test_optimized_python_refused(self):
        import subprocess
        for name in ['voice_oci.py','package-voice-image.py']:
            done=subprocess.run([sys.executable,'-O',str(HERE/name)],capture_output=True,text=True,timeout=5)
            self.assertNotEqual(done.returncode,0);self.assertIn('assertions disabled',done.stderr)
    def test_corrupt_base_refused(self):
        self.fixture()
        with self.base.open('r+b') as f:f.seek(2048);f.write(b'corrupt')
        with self.assertRaises((AssertionError,ValueError,tarfile.TarError,KeyError)):v.derive(self.base,self.out,b'new',self.pin,'ghcr.io/example/fake')

if __name__=='__main__':unittest.main()
