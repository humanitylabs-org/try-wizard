"""Release guest archive verification must finish even when tar padding exceeds the pipe buffer.
Regression: the release build hung in pack() because tarfile stops at the end-of-archive
marker and xz then blocked writing the remaining padding, timing out after 30 s."""
import hashlib, importlib.util, io, os, shutil, subprocess, sys, tarfile, tempfile, unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('assemble',HERE/'assemble.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
XZ=shutil.which('xz')

def make(tmp,members,trailer):
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as t:
        for name,data in members.items():
            info=tarfile.TarInfo(name);info.size=len(data);t.addfile(info,io.BytesIO(data))
    path=Path(tmp)/'a.tar.xz'
    path.write_bytes(subprocess.run([XZ,'-c'],input=raw.getvalue()+trailer,capture_output=True,check=True).stdout)
    return path

@unittest.skipUnless(XZ,'xz required')
class StreamMembers(unittest.TestCase):
    members={'manifest.json':b'{}','rootfs.img':b'r'*5000,'bom.json':b'{}'}
    def test_large_zero_padding_after_end_marker_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen=m.stream_members(make(tmp,self.members,b'\0'*(4*1024*1024)),list(self.members),XZ)
        self.assertEqual(seen['rootfs.img'],hashlib.sha256(b'r'*5000).hexdigest())
    def test_non_zero_data_after_end_marker_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                m.stream_members(make(tmp,self.members,b'\0'*2048+b'smuggled'),list(self.members),XZ)
    def test_missing_or_unexpected_members_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            short=dict(self.members);short.pop('bom.json')
            with self.assertRaises(AssertionError):m.stream_members(make(tmp,short,b''),list(self.members),XZ)
            extra=dict(self.members,**{'evil':b'x'})
            with self.assertRaises(AssertionError):m.stream_members(make(tmp,extra,b''),list(self.members),XZ)

def pax_record(key,value):
    body=(' %s=%s\n'%(key,value)).encode();n=len(body)
    while len(str(n).encode())+len(body)!=n:n=len(str(n).encode())+len(body)
    return str(n).encode()+body

def header(name,size,kind=b'0'):
    h=bytearray(512);h[:len(name)]=name.encode();h[100:108]=b'0000644\0';h[124:136]=('%011o\0'%size).encode()
    h[156:157]=kind;h[257:263]=b'ustar\0';h[263:265]=b'00';h[148:156]=b' '*8
    h[148:156]=('%06o\0 '%sum(h)).encode();return bytes(h)

def pad(b):return b+bytes(-len(b)%512)

def libarchive_sparse(real,segments,with_size=True):
    """Shape libarchive (macOS /usr/bin/tar) writes: pax GNU.sparse 1.0 plus a pax 'size' that
    counts the sparse map block, which is what made Python tarfile overshoot."""
    data=b''.join(real[o:o+l] for o,l in segments)
    smap=pad(('%d\n'%len(segments)+''.join('%d\n%d\n'%(o,l) for o,l in segments)).encode())
    stored=len(smap)+len(data)
    recs=b''.join(pax_record(k,v) for k,v in [('GNU.sparse.major','1'),('GNU.sparse.minor','0'),
        ('GNU.sparse.name','rootfs.img'),('GNU.sparse.realsize',str(len(real)))]+([('size',str(stored))] if with_size else []))
    return header('PaxHeader/rootfs.img',len(recs),b'x')+pad(recs)+header('GNUSparseFile.0/rootfs.img',stored)+pad(smap+data)

def regular(name,data):return header(name,len(data))+pad(data)

@unittest.skipUnless(XZ,'xz required')
class SparseMembers(unittest.TestCase):
    real=b'A'*4096+bytes(600000)+b'B'*1000+bytes(70000)
    segments=[(0,4096),(604096,1000),(len(real),0)]
    def archive(self,tmp,body):
        path=Path(tmp)/'s.tar.xz'
        path.write_bytes(subprocess.run([XZ,'-c'],input=body+bytes(1024)+bytes(9216),capture_output=True,check=True).stdout)
        return path
    def test_libarchive_sparse_with_pax_size_then_more_members(self):
        for with_size in (True,False):
            body=regular('manifest.json',b'{}')+libarchive_sparse(self.real,self.segments,with_size)+regular('boot/vmlinux',b'k'*777)+regular('bom.json',b'{}')
            with tempfile.TemporaryDirectory() as tmp:
                seen=m.stream_members(self.archive(tmp,body),['manifest.json','rootfs.img','boot/vmlinux','bom.json'],XZ)
            self.assertEqual(seen['rootfs.img'],hashlib.sha256(self.real).hexdigest())
            self.assertEqual(seen['boot/vmlinux'],hashlib.sha256(b'k'*777).hexdigest())
    def test_python_tarfile_misreads_the_libarchive_shape(self):
        # Documents why stream_members does not use tarfile: members after the sparse entry are lost.
        body=regular('manifest.json',b'{}')+libarchive_sparse(self.real,self.segments)+regular('boot/vmlinux',b'k'*777)+regular('bom.json',b'{}')
        names=[]
        try:
            with tarfile.open(fileobj=io.BytesIO(body+bytes(10240)),mode='r|') as t:names=[x.name for x in t]
        except tarfile.TarError:pass
        self.assertNotEqual(names,['manifest.json','rootfs.img','boot/vmlinux','bom.json'])
    def test_real_tar_sparse_archive(self):
        tar=shutil.which('bsdtar') or ('/usr/bin/tar' if sys.platform=='darwin' else None)
        gnu=None if tar else shutil.which('tar')
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'src';src.mkdir()
            with (src/'rootfs.img').open('wb') as f:
                f.write(b'A'*65536);f.seek(64*1024*1024);f.write(b'B'*65536);f.truncate(96*1024*1024)
            (src/'bom.json').write_bytes(b'{}')
            argv=[tar,'-cf','-','--format','pax'] if tar else [gnu,'--sparse','--sparse-version=1.0','-H','pax','-cf','-']
            raw=subprocess.run(argv+['-C',str(src),'rootfs.img','bom.json'],capture_output=True,check=True,env={**os.environ,'COPYFILE_DISABLE':'1'}).stdout
            path=Path(tmp)/'r.tar.xz';path.write_bytes(subprocess.run([XZ,'-c'],input=raw,capture_output=True,check=True).stdout)
            seen=m.stream_members(path,['rootfs.img','bom.json'],XZ)
            want=hashlib.sha256((src/'rootfs.img').read_bytes()).hexdigest()
        self.assertEqual(seen['rootfs.img'],want)

if __name__=='__main__':unittest.main()
