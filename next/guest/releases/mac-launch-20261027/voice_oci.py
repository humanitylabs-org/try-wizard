"""Native candidate OCI derivation: append a tiny layer, never reload the base.
All old compressed blobs remain byte-identical; no image/model build or fetch.
"""
import hashlib,io,json,posixpath,tarfile
from pathlib import Path
if not __debug__:raise SystemExit('refusing to run with assertions disabled')
import local_oci as oci


def encoded(value):return json.dumps(value,separators=(',',':'),sort_keys=True).encode()
def digest(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def blob_path(value):return 'blobs/sha256/'+value.split(':',1)[1]
def add(archive,name,raw,mode=0o644):
    info=tarfile.TarInfo(name);info.size=len(raw);info.mode=mode;info.uid=info.gid=info.mtime=0
    archive.addfile(info,io.BytesIO(raw))


def derive(base, output, replacement, predecessor, repository):
    old=oci.verify_archive(base)
    with tarfile.open(base) as archive:
        index=json.load(archive.extractfile('index.json'));desc=index['manifests'][0]
        assert desc['digest']==old['manifestDigest'],'Wrapped base index is unsupported'
        manifest=json.load(archive.extractfile(blob_path(desc['digest'])))
        config=json.load(archive.extractfile(blob_path(manifest['config']['digest'])))
        assert config['architecture']=='arm64' and config['os']=='linux'
        # Resolve layer ordering/whiteouts, not a convenient earlier COPY. Only
        # source bytes are read; graph/dependency files are neither extracted nor
        # recompressed. Track final path kinds to reject redirected source dirs.
        paths={};sources={}
        for layer in manifest['layers']:
            entries=[];deletes=[];changes={}
            with tarfile.open(fileobj=archive.extractfile(blob_path(layer['digest'])),mode='r|*') as contents:
                for member in contents:
                    name=member.name.removeprefix('./').rstrip('/')
                    if not name or name.startswith('/') or '..' in Path(name).parts:raise ValueError('Unsafe inherited layer path')
                    parent,leaf=posixpath.split(name)
                    if leaf=='.wh..wh..opq':deletes.append((parent,True));continue
                    if leaf.startswith('.wh.'):deletes.append((posixpath.join(parent,leaf[4:]),False));continue
                    kind='file' if member.isfile() else 'dir' if member.isdir() else 'link'
                    entries.append((name,kind))
                    if name.endswith('/speaches/executors/parakeet.py'):
                        if not member.isfile():raise ValueError('Redirected Parakeet source')
                        changes[name]=hashlib.sha256(contents.extractfile(member).read()).hexdigest()
            for target,opaque in deletes:
                for name in list(paths):
                    if name.startswith(target+'/') or (not opaque and name==target):paths.pop(name);sources.pop(name,None)
            for name,kind in entries:paths[name]=kind
            sources.update(changes)
        candidates=[name for name,value in sources.items() if value==predecessor and paths.get(name)=='file']
        assert len(candidates)==1,'Expected exactly one final pinned Parakeet source'
        source=candidates[0]
        assert all(paths.get(str(p),'dir')=='dir' for p in Path(source).parents if str(p)!='.'),'Source parent is redirected'
        parent=posixpath.dirname(source)
        pyc=[p for p in paths if (p.startswith(parent+'/__pycache__/parakeet.') and p.endswith('.pyc')) or p==source+'c']
        layer=io.BytesIO()
        with tarfile.open(fileobj=layer,mode='w',format=tarfile.USTAR_FORMAT) as patch:
            add(patch,source,replacement)
            for name in sorted(pyc):
                directory,leaf=posixpath.split(name);add(patch,posixpath.join(directory,'.wh.'+leaf),b'')
        layer_bytes=layer.getvalue();layer_digest=digest(layer_bytes)
        new_config=json.loads(json.dumps(config));new_config['rootfs']['diff_ids'].append(layer_digest)
        new_config.setdefault('history',[]).append({'created_by':'Wizard secured pinned local Parakeet source overlay'})
        assert new_config['config']==config['config'],'Runtime config must be identical'
        config_bytes=encoded(new_config);config_digest=digest(config_bytes)
        new_manifest=json.loads(json.dumps(manifest));new_manifest['config'].update(digest=config_digest,size=len(config_bytes))
        new_manifest['layers'].append({'mediaType':'application/vnd.oci.image.layer.v1.tar','digest':layer_digest,'size':len(layer_bytes)})
        manifest_bytes=encoded(new_manifest);manifest_digest=digest(manifest_bytes)
        new_index=json.loads(json.dumps(index));new_index['manifests'][0].update(digest=manifest_digest,size=len(manifest_bytes))
        # Never repoint the historical ':latest' name while importing a new
        # candidate. Bind the actual computed digest, not a guessed image ID.
        annotations=new_index['manifests'][0].setdefault('annotations',{})
        annotations['io.containerd.image.name']=repository+'@'+manifest_digest
        annotations.pop('org.opencontainers.image.ref.name',None)
        with tarfile.open(output,'x',format=tarfile.PAX_FORMAT) as result:
            for member in archive:
                if member.isfile() and (member.name=='oci-layout' or member.name.startswith('blobs/sha256/')):
                    result.addfile(member,archive.extractfile(member))
            add(result,blob_path(layer_digest),layer_bytes)
            add(result,blob_path(config_digest),config_bytes)
            add(result,blob_path(manifest_digest),manifest_bytes)
            add(result,'index.json',encoded(new_index))
    verified=oci.verify_archive(output)
    assert verified['config']['config']==config['config']
    assert verified['config']['rootfs']['diff_ids'][:-1]==config['rootfs']['diff_ids']
    return verified,{'sourcePath':'/'+source,'removedBytecode':sorted(pyc),'baseDigest':old['digest'],
        'baseConfigDigest':old['configDigest'],'baseLayers':manifest['layers'],'newLayerDigest':layer_digest}
