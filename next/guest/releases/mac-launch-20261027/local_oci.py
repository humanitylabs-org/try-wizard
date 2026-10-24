"""Credential-free local OCI transport. Never push, login or fall back to Docker Hub."""
import hashlib, json, os, re, subprocess, tarfile, uuid
from contextlib import contextmanager
from pathlib import Path
DOCKER='/opt/homebrew/bin/docker'
SOCKET='unix:///Users/thales/.colima/default/docker.sock'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(argv,env=None,timeout=120):
    return subprocess.check_output(list(map(str,argv)),env=env,text=True,timeout=timeout).strip()

def environment(out):
    # Empty inline auth config avoids keychain discovery; retain buildx instance metadata,
    # and select context explicitly (DOCKER_HOST alone + --builder colima is rejected).
    out=Path(out);cfg=out/'docker-config';cfg.mkdir(exist_ok=True)
    (cfg/'config.json').write_text('{"auths":{},"credsStore":""}\n')
    plugins=cfg/'cli-plugins';plugins.mkdir(exist_ok=True)
    plugin=next(p for p in [Path('/opt/homebrew/lib/docker/cli-plugins/docker-buildx'),Path.home()/'.docker/cli-plugins/docker-buildx'] if p.exists())
    if not (plugins/'docker-buildx').exists():(plugins/'docker-buildx').symlink_to(plugin.resolve())
    # Docker driver can be addressed by the explicit endpoint without copying context/auth state.
    return {**os.environ,'PATH':'/opt/homebrew/bin:'+os.environ.get('PATH',''),'DOCKER_HOST':SOCKET,'DOCKER_CONFIG':str(cfg),'TMPDIR':str(out),'BUILDX_BUILDER':'default'}

def mirror(ref,env,records):
    """Resolve tags on mirrors only; pinned digests must survive the move byte-for-byte."""
    if ref=='scratch':return ref
    first=ref.split('/')[0]
    qualified='/' in ref and ('.' in first or ':' in first or first=='localhost')
    hub=not qualified or first in ('docker.io','index.docker.io')
    if not hub:return ref  # GHCR upstreams remain anonymous, never publication prerequisites.
    name=ref.removeprefix('docker.io/').removeprefix('index.docker.io/')
    if '/' not in name:name='library/'+name
    failures=[]
    for prefix in ('mirror.gcr.io/','public.ecr.aws/docker/'):
        candidate=prefix+name
        try:
            obj=json.loads(run([DOCKER,'buildx','imagetools','inspect',candidate,'--format','{{json .Manifest}}'],env))
            digest=obj['digest'];assert re.fullmatch('sha256:[0-9a-f]{64}',digest)
            if '@' in ref:assert digest==ref.split('@')[1], 'mirror changed pinned digest'
            repo=candidate.split('@')[0];repo=re.sub(r':[^/:]+$','',repo)
            exact=repo+'@'+digest
            records[ref]={'resolved':exact,'digest':digest,'mirror':prefix.rstrip('/')}
            return exact
        except (subprocess.SubprocessError,ValueError,AssertionError,KeyError) as exc:failures.append(type(exc).__name__+': '+str(exc))
    raise RuntimeError('no verified mirror for '+ref+': '+repr(failures))

def verify_archive(path):
    """Stream and hash all OCI blobs; inspect the actual arm64 config, no extraction."""
    blobs={};index=None
    with tarfile.open(path,'r|*') as tar:
        for m in tar:
            if not m.isfile():continue
            f=tar.extractfile(m);assert f is not None
            if m.name=='index.json':index=f.read();continue
            if not m.name.startswith('blobs/sha256/'):continue
            h=hashlib.sha256();small=bytearray()
            for chunk in iter(lambda:f.read(8*1024*1024),b''):
                h.update(chunk)
                if m.size<4*1024*1024:small.extend(chunk)
            digest='sha256:'+h.hexdigest();assert m.name=='blobs/sha256/'+h.hexdigest(),'corrupt OCI blob'
            blobs[digest]=(m.size,bytes(small))
    assert index is not None
    doc=json.loads(index);assert len(doc['manifests'])==1,'single-platform OCI required'
    descriptor=doc['manifests'][0];digest=descriptor['digest']
    def get(desc):
        size,data=blobs[desc['digest']];assert size==desc['size'];return json.loads(data)
    manifest=get(descriptor)
    # BuildKit may emit a one-child index even without provenance.
    if 'manifests' in manifest:
        assert len(manifest['manifests'])==1;descriptor=manifest['manifests'][0];manifest=get(descriptor)
    config=get(manifest['config']);assert config['architecture']=='arm64' and config['os']=='linux'
    for layer in manifest.get('layers') or []:assert blobs[layer['digest']][0]==layer['size']
    return {'digest':digest,'manifestDigest':descriptor['digest'],'indexSha256':hashlib.sha256(index).hexdigest(),'configDigest':manifest['config']['digest'],'config':config}

def validate(root,row):
    assert row['transport']=='oci-archive' and row['archiveVerified'] is True and row['loadVerified'] is True
    path=(Path(root)/row['archive']).resolve();assert path.is_relative_to(Path(root).resolve())
    assert sha(path)==row['archiveSha256'],'archive hash mismatch'
    actual=verify_archive(path)
    for k in ['digest','manifestDigest','indexSha256','configDigest']:assert actual[k]==row[k],k
    return path

def local_base(root,target,pins):
    """Validate a source-built dependency; never silently fall back to its private registry."""
    key=target['baseComponent']
    assert key in pins['finalPins']
    assert target['sourceCommit']==pins['finalPins'][key]
    path=Path(root)/'image-packaging'/key/'result.json'
    row=json.loads(path.read_text())
    assert row['component']==key and row['sourceCommit']==pins['finalPins'][key]
    assert row['ref']==target['baseRef'] and row['tagsPublished'] is False
    validate(root,row)
    return row,{'receipt':str(path.relative_to(root)),'receiptSha256':sha(path),'sourceCommit':row['sourceCommit'],'digest':row['digest']}

def load(root,row,docker='docker',env=None):
    path=validate(root,row)
    run([docker,'load','-i',path],env,timeout=600)
    exact=row['ref']+'@'+row['digest']
    obj=json.loads(run([docker,'image','inspect',exact],env))[0]
    assert obj['Architecture']=='arm64' and exact in obj.get('RepoDigests',[]),'daemon must preserve OCI digest (containerd store required)'
    return obj

@contextmanager
def probe_mount(files,image,env):
    """Colima does not share external-media bind paths: copy scripts to a daemon volume."""
    volume='mac-oci-probe-'+uuid.uuid4().hex;container=volume+'-copy'
    run([DOCKER,'volume','create',volume],env)
    try:
        run([DOCKER,'create','--name',container,'-v',volume+':/opt/wizard-probe',image],env)
        try:
            for file in files:run([DOCKER,'cp',file,container+':/opt/wizard-probe/'+Path(file).name],env)
        finally:run([DOCKER,'rm',container],env)
        yield volume+':/opt/wizard-probe:ro'
    finally:run([DOCKER,'volume','rm',volume],env)

def export(out,context,image,env,extra=()):
    out=Path(out);archive=out/'image.oci.tar'
    argv=[DOCKER,'buildx','build','--platform','linux/arm64','--provenance=false','--metadata-file',out/'metadata.json','--output','type=oci,name='+image+',dest='+str(archive),*extra,str(context)]
    with (out/'build.log').open('w') as log:subprocess.run(list(map(str,argv)),env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=780)
    data=verify_archive(archive);meta=json.loads((out/'metadata.json').read_text());assert meta['containerimage.digest']==data['digest']
    result={k:v for k,v in data.items() if k!='config'}
    result.update(transport='oci-archive',archive=str(archive),archiveSha256=sha(archive),archiveVerified=True,loadVerified=True,ref=image,tagsPublished=False,releasePublished=False)
    # Root-independent temporary row for the same verified loader used in the guest.
    obj=load(out,{**result,'archive':archive.name},DOCKER,env)
    result['imageId']=obj['Id']
    return result,obj
