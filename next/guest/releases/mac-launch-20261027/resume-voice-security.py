#!/usr/bin/env python3
"""Failed-phase-only trust recovery. Never derive, import, load or start a daemon.
The caller seals request bytes, retained metadata and original source/evidence.
Only per-container DNS may use the observed existing host resolver; no fallback.
"""
import argparse, hashlib, importlib.util, io, ipaddress, json, os, platform, re
import subprocess, sys, tarfile, time, uuid
from pathlib import Path
if not __debug__:raise SystemExit('refusing optimized recovery')
sys.dont_write_bytecode=True
DOCKER='/opt/homebrew/bin/docker'
SOCKET='unix:///Users/thales/.colima/wizard-agents/docker.sock'
FIELDS=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')

def need(value, message):
    if not value:raise RuntimeError(message)
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def metadata(p):
    s=Path(p).lstat();need(Path(p).is_file() and not Path(p).is_symlink(),'nonregular retained input')
    return {k:getattr(s,k) for k in FIELDS}
def save(p, data):
    with Path(p).open('x') as f:json.dump(data,f,indent=2,sort_keys=True);f.write('\n')
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def host_resolver(text):
    # scutil default resolver only, not split-tailnet/search/scoped routes.
    default=text.split('DNS configuration (for scoped queries)')[0].split('resolver #1\n',1)[1].split('\nresolver #',1)[0]
    need(not re.search(r'^\s*domain\s*:',default,re.M),'split resolver cannot replace default route')
    values=re.findall(r'^\s*nameserver\[\d+\]\s*:\s*(\S+)',default,re.M)
    need(len(values)==1,'ambiguous host default resolver')
    value=values[0];need(ipaddress.ip_address(value).is_private and not ipaddress.ip_address(value).is_loopback,'nonprivate resolver refused')
    return value

def tag_rows(text):
    return sorted(tuple(x.get(k) for k in ('Repository','Tag','ID','Digest')) for x in (json.loads(l) for l in text.splitlines() if l.strip()) if x.get('Tag') not in ('<none>','',None))

def preserved_config(old,new):
    need(old['config']==new['config'],'runtime configuration changed')
    a=json.loads(json.dumps(old));b=json.loads(json.dumps(new))
    a.pop('history',None);b.pop('history',None)
    need(b['rootfs']['diff_ids'][:-1]==a['rootfs']['diff_ids'],'old rootfs changed')
    b['rootfs']['diff_ids']=b['rootfs']['diff_ids'][:-1]
    need(a==b,'nonoverlay config changed')
    need(new['history'][:-1]==old.get('history',[]),'old history changed')

def probe_argv(exact,name,dns,entrypoint):
    ipaddress.ip_address(dns)
    need(re.fullmatch(r'ghcr\.io/humanitylabs-org/wizard-mac-security-transcriber@sha256:[0-9a-f]{64}',exact),'noncandidate image')
    return [DOCKER,'run','--pull=never','--rm','--name',name,'-i','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--dns',dns,'--entrypoint',entrypoint,exact,'-s' if entrypoint=='/bin/sh' else '-']

def archive_manifest(path,verified):
    with tarfile.open(path) as t:
        return json.load(t.extractfile('blobs/sha256/'+verified['manifestDigest'].split(':')[1]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--request-sha256',required=True);a=p.parse_args()
    need(platform.system()=='Darwin' and platform.machine()=='arm64','native ARM required')
    need(os.environ.get('WIZARD_WORKER_LANE')=='light','parent light admission required')
    need(sha(a.request)==a.request_sha256,'request drift');q=json.loads(a.request.read_text())
    root=a.request.resolve().parent;out=root/'recovery-evidence';out.mkdir(mode=0o700)
    deadline=time.monotonic()+850
    result={'success':False,'requestSha256':a.request_sha256,'sourceStageSha256':q['sourceStageSha256'],'source':q['source'],'harnessRevision':q['harnessRevision'],'published':False,'ownerActivation':False,'voiceTranscriptionAccepted':False,'rebuild':False,'reimport':False}
    env={'PATH':'/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin','HOME':os.environ['HOME'],'DOCKER_HOST':SOCKET,'DOCKER_CONFIG':str(root/'docker-config'),'TMPDIR':str(out),'PYTHONDONTWRITEBYTECODE':'1'}
    cfg=Path(env['DOCKER_CONFIG']);cfg.mkdir(mode=0o700);(cfg/'config.json').write_text('{"auths":{},"credsStore":""}\n')
    def run(argv,timeout=20):
        return subprocess.check_output(list(map(str,argv)),env=env,text=True,timeout=min(timeout,max(1,deadline-time.monotonic()))).strip()
    def snapshots():
        host=run(['/usr/sbin/scutil','--dns']);guest=run(['/opt/homebrew/bin/colima','--profile','wizard-agents','ssh','--','cat','/etc/resolv.conf'])
        need(host_resolver(host)==q['dns'],'host resolver drift')
        need(guest==q['daemonResolvConf'],'daemon resolver drift')
        return {'host':host,'daemon':guest,'perContainerDNS':q['dns'],'workaroundNotProvenRootCause':True}
    def tags():return run([DOCKER,'image','ls','--no-trunc','--digests','--format','{{json .}}',q['ref']])
    def check_retained():
        for path,row in q['retained'].items():
            need(metadata(path)==row['metadata'],'retained metadata drift: '+path)
            if row.get('sha256'):need(sha(path)==row['sha256'],'retained bytes drift: '+path)
    def check_sources():
        for path,row in q['sourceFiles'].items():
            need(not Path(path).is_symlink() and sha(path)==row['sha256'] and (Path(path).stat().st_mode&0o777)==row['mode'],'source/evidence drift: '+path)
    def probe(label,entrypoint,source,timeout):
        name='voice-trust-a3-'+uuid.uuid4().hex
        argv=probe_argv(exact,name,q['dns'],entrypoint)
        try:
            r=subprocess.run(argv,input=source,text=True,capture_output=True,env=env,timeout=min(timeout,max(1,deadline-time.monotonic()-40)))
            (out/(label+'.log')).write_text(r.stdout+r.stderr)
            need(r.returncode==0,label+' failed; no fallback route or trust waiver')
        except subprocess.TimeoutExpired as e:
            (out/(label+'.log')).write_bytes((e.stdout or b'')+(e.stderr or b''));raise RuntimeError(label+' timeout; inconclusive, not certificate rejection')
        finally:
            # Exact random owned name only. --rm normally already removed it.
            ids=run([DOCKER,'ps','-aq','--filter','name=^/'+name+'$'])
            if ids:run([DOCKER,'rm','-f',name])
            need(not run([DOCKER,'ps','-aq','--filter','name=^/'+name+'$']),'owned probe cleanup incomplete')
    try:
        check_retained();check_sources()
        need(sha(q['sourceStageManifest'])==q['sourceStageSha256'],'original stage changed')
        stage=json.loads(Path(q['sourceStageManifest']).read_text())
        for rel,h in stage['files'].items():
            path=Path(q['sourceStageManifest']).parent/rel
            need(sha(path)==h and (path.stat().st_mode&0o777)==stage['fileModes'][rel],'original stage closure drift')
        proof=json.loads(Path(q['forumProof']).read_text())
        need(sha(q['forumProof'])==q['forumProofSha256'] and proof['success'] is True and proof['testsRun']==75 and proof['skipped']==0 and proof['source']==q['source'] and proof['stageSha256']==q['sourceStageSha256'],'inherited source proof mismatch')
        need(proof['sourceClosureSha256']==sha(Path(q['sourceStageManifest']).parent/'source-closure.json') and proof['inheritedHttpClosureSha256']==sha(Path(q['sourceStageManifest']).parent/'inherited-http-closure.json'),'inherited test closure mismatch')
        failed=json.loads(Path(q['failedResult']).read_text());need(failed['success'] is False and failed['error']=='image failed; inspect raw log','not exact historical failure')
        need(Path(q['imageRoot'],'security.log').read_text()=='curl: (6) Could not resolve host: example.com\n','not the DNS failure')
        result['inherited']={'sourceTests':75,'unchangedHTTP':15,'forumProofSha256':q['forumProofSha256'],'failedJobId':q['failedJobId'],'phases':['OCI derivation','new-image import','protected tags equality','runtime configuration equality','raw adapter SourceFileLoader/ubuntu/no-pyc identity','marker 1'],'failedEvidenceBindings':q['retained']}
        need(run([DOCKER,'info','--format','{{.ID}}'])==q['daemonID'],'daemon identity changed')
        need(run([DOCKER,'info','--format','{{.Architecture}}'])=='aarch64','native daemon architecture changed')
        initial_dns=snapshots();save(out/'resolver-before.json',initial_dns)
        initial_tags=tags();need(tag_rows(initial_tags)==tag_rows(Path(q['imageRoot'],'images-before.jsonl').read_text())==tag_rows(Path(q['imageRoot'],'images-after.jsonl').read_text()),'protected tags changed')
        save(out/'tags-before.json',{'raw':initial_tags})
        launch=Path(q['launch']);need(not list(launch.glob('__pycache__/*.pyc')),'unbound host bytecode refused')
        sys.path.insert(0,str(launch));oci=module('recovery_oci',launch/'local_oci.py');sys.modules['local_oci']=oci
        package=module('recovery_package',launch/'package-voice-image.py')
        base_receipt=Path(q['baseReceipt']);old=json.loads(base_receipt.read_text())
        need(sha(base_receipt)==q['baseReceiptSha256'] and old['ref']+'@'+old['digest']==package.BASE and old['archiveSha256']==q['baseArchiveSha256'],'predecessor receipt drift')
        base_archive=oci.validate(base_receipt.parents[2],old)
        original=oci.verify_archive(base_archive);archive=Path(q['imageRoot'],'image.oci.tar');verified=oci.verify_archive(archive)
        need(verified['digest']==q['digest'] and verified['manifestDigest']==q['manifestDigest'] and verified['configDigest']==q['configDigest'],'candidate digest/config binding changed')
        derivation=json.loads(Path(q['imageRoot'],'derivation.json').read_text())
        old_manifest=archive_manifest(base_archive,original);new_manifest=archive_manifest(archive,verified)
        need(original['manifestDigest']==old['manifestDigest'] and original['configDigest']==derivation['baseConfigDigest'] and original['digest']==derivation['baseDigest'],'old manifest/config mismatch')
        need(new_manifest['layers'][:-1]==old_manifest['layers']==derivation['baseLayers'] and new_manifest['layers'][-1]['digest']==derivation['newLayerDigest'],'layers changed')
        preserved_config(original['config'],verified['config'])
        need(verified['config']['rootfs']['diff_ids'][-1]==derivation['newLayerDigest'],'overlay diff ID changed')
        with tarfile.open(archive) as t:
            with tarfile.open(fileobj=t.extractfile('blobs/sha256/'+derivation['newLayerDigest'].split(':')[1])) as layer:
                allowed={derivation['sourcePath'].lstrip('/')}|{str(Path(x).parent/('.wh.'+Path(x).name)) for x in derivation['removedBytecode']}
                need({x.name for x in layer.getmembers()}==allowed and all(x.isfile() for x in layer.getmembers()),'unexpected overlay members')
                source=layer.extractfile(derivation['sourcePath'].lstrip('/')).read()
                need(source==(launch/'voice-parakeet.py').read_bytes(),'adapter source changed')
        expected=sha(launch/'voice-parakeet.py');identity=json.loads(Path(q['imageRoot'],'identity.json').read_text())
        need(identity=={'path':derivation['sourcePath'],'sha256':expected,'loader':'SourceFileLoader','user':'ubuntu','bytecode':[]},'inherited loaded identity mismatch')
        exact=q['ref']+'@'+verified['digest'];built=json.loads(run([DOCKER,'image','inspect',exact]))[0]
        need(built['Id']==q['imageId'] and exact in built['RepoDigests'] and built['Architecture']=='arm64','retained imported image mismatch')
        for k in ('User','Entrypoint','Cmd','Env','WorkingDir','Labels','Volumes'):
            need((built['Config'].get(k) or None)==(verified['config']['config'].get(k) or None),'daemon runtime config mismatch: '+k)
        need(built['Config']['User']=='ubuntu','nonroot changed')
        # All DNS dependencies through the single existing host route, before TLS.
        security=module('recovery_security',launch/'security-closure.py')
        hosts=['example.com','probe-emudhra.we-have-a-problem.com']+[h+'.we-have-a-problem.com' for h in security.BAD]
        dns_source="import socket,json;from pathlib import Path;h="+repr(hosts)+";r=Path('/etc/resolv.conf').read_text();assert [l.split()[1] for l in r.splitlines() if l.startswith('nameserver ')]==["+repr(q['dns'])+"];print(json.dumps({'resolvConf':r,'hosts':{x:sorted({a[4][0] for a in socket.getaddrinfo(x,443,type=socket.SOCK_STREAM)}) for x in h}}))"
        probe('dns-preflight','python',dns_source,45)
        probe('security','/bin/sh',security.PROBE,470)
        probe('active-python-security','python',(launch/'security-probe.py').read_text(),260)
        check_sources();check_retained();need(tag_rows(tags())==tag_rows(initial_tags),'protected tag drift')
        need(snapshots()==initial_dns,'resolver state changed')
        save(out/'resolver-after.json',initial_dns)
        transport={k:v for k,v in verified.items() if k!='config'}
        row={**transport,'transport':'oci-archive','archive':str(archive),'archiveSha256':sha(archive),'archiveVerified':True,'loadVerified':True,'ref':q['ref'],'imageId':built['Id'],'tagsPublished':False,'releasePublished':False,'base':package.BASE,'key':'transcriber','predecessorSourceSha256':package.PREDECESSOR,'voiceSourceSha256':expected,'recipeSha256':sha(Path(q['imageRoot'],'derivation.json')),'baseReceiptSha256':sha(base_receipt),'baseArchiveSha256':old['archiveSha256'],'derivation':derivation,'configPreserved':True,'baseLayersPreserved':True,'staleBytecodeRejected':True,'securityPassed':True,'securityLogSha256':sha(out/'security.log'),'activePythonSecurityLogSha256':sha(out/'active-python-security.log'),'voiceTranscriptionAccepted':False,'ownerActivation':False,'recoveryRequestSha256':a.request_sha256,'inheritedFromFailedJob':q['failedJobId'],'reimported':False,'resolverWorkaround':initial_dns}
        receipt=Path(q['imageRoot'],'result-recovery-a3.json');save(receipt,row)
        resolver=module('recovery_resolve',launch/'resolve-voice-package.py')
        resolver.resolve(receipt,Path(q['native']),out/'voice-package')
        check_retained();check_sources();need(tag_rows(tags())==tag_rows(initial_tags) and snapshots()==initial_dns,'post-resolution state drift')
        result.update(success=True,imageReceipt=str(receipt),imageReceiptSha256=sha(receipt),resolvedFilesSha256=sha(out/'voice-package/resolved-files.json'),selection=json.loads((out/'voice-package/selected-engine.json').read_text()),image=row)
    except BaseException as e:
        result.update(errorClass=type(e).__name__,error=str(e)[:600]);raise
    finally:
        preservation_error=None
        try:
            check_retained();check_sources();result['retainedMetadataAndSmallBytesPreserved']=True
            if 'initial_dns' in locals():
                current=snapshots();save(out/'resolver-final.json',current)
                need(current==initial_dns,'final resolver drift');result['resolversPreserved']=True
            if 'initial_tags' in locals():
                final_tags=tags();save(out/'tags-final.json',{'raw':final_tags})
                need(tag_rows(final_tags)==tag_rows(initial_tags),'final protected tag drift');result['protectedTagsPreserved']=True
        except BaseException as e:
            preservation_error=e;result['success']=False;result['preservationError']=str(e)[:600]
        result['finished']=time.time();save(out/'result.json',result)
        if preservation_error:raise RuntimeError('retained state preservation incomplete') from preservation_error

if __name__=='__main__':main()
