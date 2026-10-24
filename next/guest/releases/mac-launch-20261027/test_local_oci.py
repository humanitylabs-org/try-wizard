"""Synthetic OCI unit fixtures, never acceptance evidence or published images."""
import hashlib, io, json, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import local_oci as oci

def fixture_archive(root,ref,identity):
    root=Path(root);archive=root/('unit-'+identity+'.oci.tar');blobs={}
    def blob(obj,kind):
        data=json.dumps(obj).encode();digest='sha256:'+hashlib.sha256(data).hexdigest();blobs[digest]=data
        return {'mediaType':kind,'digest':digest,'size':len(data)}
    config=blob({'architecture':'arm64','os':'linux','config':{'Labels':{'unitFixtureOnly':identity}},'rootfs':{'type':'layers','diff_ids':[]}},'application/vnd.oci.image.config.v1+json')
    manifest=blob({'schemaVersion':2,'config':config,'layers':None},'application/vnd.oci.image.manifest.v1+json')
    index=json.dumps({'schemaVersion':2,'manifests':[manifest]}).encode()
    with tarfile.open(archive,'w') as t:
        for name,data in [('index.json',index),('oci-layout',b'{"imageLayoutVersion":"1.0.0"}'),*[('blobs/sha256/'+k[7:],v) for k,v in blobs.items()]]:
            m=tarfile.TarInfo(name);m.size=len(data);t.addfile(m,io.BytesIO(data))
    row={k:v for k,v in oci.verify_archive(archive).items() if k!='config'}
    row.update(ref=ref,archive=archive.name,archiveSha256=oci.sha(archive),transport='oci-archive',archiveVerified=True,loadVerified=True,tagsPublished=False,imageId=manifest['digest'],unitFixtureOnly=True)
    return row

class LocalOCITests(unittest.TestCase):
    def test_archive_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            row=fixture_archive(d,'unit.invalid/test','transport');p=oci.validate(d,row)
            p.write_bytes(p.read_bytes()+b'tamper')
            with self.assertRaisesRegex(AssertionError,'archive hash'):oci.validate(d,row)
    def test_archive_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as d:
            row=fixture_archive(d,'unit.invalid/test','escape');row['archive']='../outside.oci.tar'
            with self.assertRaises(AssertionError):oci.validate(d,row)
    def test_pinned_base_only_resolves_unchanged_mirror_digest(self):
        digest='sha256:'+'a'*64
        with patch.object(oci,'run',return_value=json.dumps({'digest':digest})) as run:
            records={};got=oci.mirror('python:3.12-alpine@'+digest,{},records)
            self.assertEqual(got,'mirror.gcr.io/library/python@'+digest)
            self.assertEqual(records['python:3.12-alpine@'+digest]['digest'],digest)
            self.assertTrue(all('docker.io' not in ' '.join(c.args[0]) for c in run.call_args_list))
    def test_no_hub_fallback_when_mirrors_fail(self):
        with patch.object(oci,'run',return_value=json.dumps({'digest':'sha256:'+'b'*64})) as run:
            with self.assertRaises(RuntimeError):oci.mirror('node@sha256:'+'a'*64,{}, {})
            self.assertEqual(run.call_count,2)
    def test_digest_load_does_not_pull(self):
        with tempfile.TemporaryDirectory() as d:
            row=fixture_archive(d,'unit.invalid/test','load')
            with patch.object(oci,'run',side_effect=['loaded',json.dumps([{'Architecture':'arm64','RepoDigests':[row['ref']+'@'+row['digest']]}])]) as run:
                oci.load(d,row)
                self.assertEqual(run.call_args_list[0].args[0][1],'load')
                self.assertFalse(any('pull' in c.args[0] for c in run.call_args_list))
if __name__=='__main__':unittest.main()
