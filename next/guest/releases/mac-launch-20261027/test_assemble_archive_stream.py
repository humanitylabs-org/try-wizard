"""Release guest archive verification must finish even when tar padding exceeds the pipe buffer.
Regression: the release build hung in pack() because tarfile stops at the end-of-archive
marker and xz then blocked writing the remaining padding, timing out after 30 s."""
import hashlib, importlib.util, io, shutil, subprocess, sys, tarfile, tempfile, unittest
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

if __name__=='__main__':unittest.main()
