#!/usr/bin/env python3
"""Candidate-only native ARM derivation of the selected, already hardened engine.
Reuses owning OCI transport/security probes; no publish, pull or base reload.
"""
import argparse, hashlib, importlib.util, json, os, re, shutil, subprocess, sys
from pathlib import Path
if not __debug__:raise SystemExit('refusing to run with assertions disabled')
import local_oci as oci
HERE = Path(__file__).resolve().parent
BASE = 'ghcr.io/humanitylabs-org/wizard-mac-security-transcriber@sha256:fe0bde3040230c526086ac5c729ad81d7ca96fc3c49d846ec27ed3a2065825f6'
PREDECESSOR = 'e1c2784dd281d338a1cadb42711527a42cb326e3e91424eb45646670b049a291'

def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def build(output):
    assert sys.platform=='darwin' and __import__('platform').machine()=='arm64'
    root=output.resolve();assert root.is_relative_to(Path('/Volumes/ThalesMedia/WizardBuilds'))
    root.mkdir(parents=True,exist_ok=False);env=oci.environment(root)
    def run(argv,**kw): return oci.run(argv,env,**kw)
    # Native preflight found the historical default daemon gone. Reuse the
    # authenticated archived secured image without loading or rebuilding it.
    import voice_oci
    base_root=Path('/Volumes/ThalesMedia/Projects/wizard-mac/guest-launch-20261027-release-83dc0e3')
    receipt=base_root/'security-packaging/transcriber/result.json'
    assert sha(receipt)=='702014b5df665c452e95adc5857d99b4d6a2af424edf68d8fe564217c5d9c213'
    before=receipt.stat();row=json.loads(receipt.read_text())
    assert row['ref']+'@'+row['digest']==BASE and row['archiveSha256']=='ba01e1609b8b8f6319d76be42b55d66486b8155c8395d2070b308d630e82cd47'
    original=oci.validate(base_root,row);metadata=original.stat()
    archive=root/'image.oci.tar'
    verified,derivation=voice_oci.derive(original,archive,(HERE/'voice-parakeet.py').read_bytes(),PREDECESSOR,BASE.split('@')[0])
    assert derivation['baseDigest']==BASE.split('@')[1]
    fields=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')
    assert all(getattr(original.stat(),f)==getattr(metadata,f) and getattr(receipt.stat(),f)==getattr(before,f) for f in fields),'Archived predecessor changed'
    # Existing native build daemon, not an owner Wizard VM. Only the NEW image
    # is imported. No Colima start/reconfigure or old archive replay is allowed.
    oci.SOCKET='unix:///Users/thales/.colima/wizard-agents/docker.sock'
    env=oci.environment(root)
    transport={k:v for k,v in verified.items() if k!='config'}
    transport.update(transport='oci-archive',archive=str(archive),archiveSha256=sha(archive),archiveVerified=True,loadVerified=True,ref=BASE.split('@')[0],tagsPublished=False,releasePublished=False)
    def images():return run([oci.DOCKER,'image','ls','--no-trunc','--digests','--format','{{json .}}',transport['ref']])
    protected=images();(root/'images-before.jsonl').write_text(protected+'\n')
    # Owning loader requires this provisional sentinel; no receipt persists
    # until its actual import/inspect gates and all security probes pass.
    built=oci.load(root,transport,oci.DOCKER,env);transport['imageId']=built['Id']
    after=images();(root/'images-after.jsonl').write_text(after+'\n')
    # Immutable import may add the new digest row, never add/repoint any tag.
    tags=lambda text:sorted(tuple(x.get(k) for k in ('Repository','Tag','ID','Digest')) for x in (json.loads(line) for line in text.splitlines() if line.strip()) if x.get('Tag') not in ('<none>','',None))
    assert tags(protected)==tags(after),'Protected repository tags changed'
    raw_config=verified['config']['config']
    for key in ('User','Entrypoint','Cmd','Env','WorkingDir','Labels','Volumes'):
        assert (built['Config'].get(key) or None)==(raw_config.get(key) or None),key
    flags=[oci.DOCKER,'run','--pull=never','--rm','--read-only','--network','none','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','python']
    probe="import hashlib,json,pwd,os;from pathlib import Path;from speaches.executors import parakeet;p=Path(parakeet.__file__);print(json.dumps({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'loader':type(parakeet.__spec__.loader).__name__,'user':pwd.getpwuid(os.getuid()).pw_name,'bytecode':[str(x) for x in p.parent.glob('__pycache__/parakeet.*.pyc')]+([str(p)+'c'] if Path(str(p)+'c').exists() else [])}))"
    exact=transport['ref']+'@'+transport['digest'];expected=sha(HERE/'voice-parakeet.py')
    imported=json.loads(run([*flags,exact,'-c',probe]))
    assert imported=={'path':derivation['sourcePath'],'sha256':expected,'loader':'SourceFileLoader','user':'ubuntu','bytecode':[]}
    (root/'identity.json').write_text(json.dumps(imported,indent=2)+'\n')
    (root/'derivation.json').write_text(json.dumps(derivation,indent=2)+'\n')
    marker=run([*flags,exact,'-c','from speaches.executors.parakeet import WIZARD_PINNED_PARAKEET; print(WIZARD_PINNED_PARAKEET)']);assert marker=='1'
    spec=importlib.util.spec_from_file_location('voice_security_closure',HERE/'security-closure.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    tls=subprocess.run([oci.DOCKER,'run','--pull=never','--rm','-i','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','/bin/sh',exact,'-s'],input=m.PROBE,text=True,capture_output=True,env=env,timeout=900)
    (root/'security.log').write_text(tls.stdout+tls.stderr);assert tls.returncode==0,'Inherited trust-client probes failed'
    active=subprocess.run([oci.DOCKER,'run','--pull=never','--rm','-i','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','python',exact,'-'],input=(HERE/'security-probe.py').read_text(),text=True,capture_output=True,env=env,timeout=300)
    (root/'active-python-security.log').write_text(active.stdout+active.stderr)
    assert active.returncode==0,'Active Speaches interpreter trust probe failed'
    row={**transport,'base':BASE,'key':'transcriber','predecessorSourceSha256':PREDECESSOR,
        'voiceSourceSha256':expected,'recipeSha256':sha(root/'derivation.json'),'baseReceiptSha256':sha(receipt),'baseArchiveSha256':row['archiveSha256'],'derivation':derivation,
        'configPreserved':True,'baseLayersPreserved':True,'staleBytecodeRejected':True,
        'securityPassed':True,'securityLogSha256':sha(root/'security.log'),'activePythonSecurityLogSha256':sha(root/'active-python-security.log'),
        'voiceTranscriptionAccepted':False,'ownerActivation':False}
    # Receipt is only written after native import, identity and trust gates pass.
    (root/'result.json').write_text(json.dumps(row,indent=2)+'\n');print(json.dumps(row))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)

if __name__=='__main__':main()
