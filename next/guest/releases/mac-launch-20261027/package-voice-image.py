#!/usr/bin/env python3
"""Candidate-only native ARM derivation of the selected, already hardened engine.
Reuses owning OCI transport/security probes; no publish, pull or base reload.
"""
import argparse, hashlib, importlib.util, json, os, re, shutil, subprocess, sys
from pathlib import Path
import local_oci as oci
HERE = Path(__file__).resolve().parent
BASE = 'ghcr.io/humanitylabs-org/wizard-mac-security-transcriber@sha256:fe0bde3040230c526086ac5c729ad81d7ca96fc3c49d846ec27ed3a2065825f6'
PREDECESSOR = 'e1c2784dd281d338a1cadb42711527a42cb326e3e91424eb45646670b049a291'

def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def recipe(path, user):
    assert re.fullmatch(r'/[a-zA-Z0-9_./-]+/parakeet.py', path)
    assert re.fullmatch(r'[a-zA-Z0-9_:-]+', user) and user not in ('0','root')
    # No package installs, certificate changes or runtime dependency replacement.
    # Delete all stale pyc variants rather than relying on timestamp invalidation.
    code = "from pathlib import Path; p=Path("+repr(path)+"); [f.unlink() for f in (p.parent/'__pycache__').glob('parakeet.*.pyc')]"
    return '\n'.join(['FROM '+BASE, 'USER 0', 'COPY --chown=0:0 --chmod=0644 voice-parakeet.py '+path,
        'RUN python -c '+__import__('shlex').quote(code), 'USER '+user])+'\n'

def build(output):
    assert sys.platform=='darwin' and __import__('platform').machine()=='arm64'
    root=output.resolve();assert root.is_relative_to(Path('/Volumes/ThalesMedia/WizardBuilds'))
    root.mkdir(parents=True,exist_ok=False);env=oci.environment(root)
    def run(argv,**kw): return oci.run(argv,env,**kw)
    base=json.loads(run([oci.DOCKER,'image','inspect',BASE]))[0]
    assert base['Architecture']=='arm64' and BASE in base.get('RepoDigests',[])
    flags=[oci.DOCKER,'run','--pull=never','--rm','--read-only','--network','none','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','python']
    probe="import inspect,hashlib,json;from speaches.executors import parakeet;print(json.dumps({'path':parakeet.__file__,'sha256':hashlib.sha256(inspect.getsource(parakeet).encode()).hexdigest()}))"
    old=json.loads(run([*flags,BASE,'-c',probe]));assert old['sha256']==PREDECESSOR
    context=root/'context';context.mkdir();shutil.copy2(HERE/'voice-parakeet.py',context/'voice-parakeet.py')
    (context/'Dockerfile').write_text(recipe(old['path'],base['Config']['User']))
    transport,built=oci.export(root,context,'ghcr.io/humanitylabs-org/wizard-mac-security-transcriber',env)
    # Config invariance is broader than a list of hand-picked fields.
    assert built['Config']==base['Config'],'Runtime config changed'
    assert built['RootFS']['Layers'][:len(base['RootFS']['Layers'])]==base['RootFS']['Layers']
    exact=transport['ref']+'@'+transport['digest'];expected=sha(HERE/'voice-parakeet.py')
    imported=json.loads(run([*flags,exact,'-c',probe]))
    assert imported=={'path':old['path'],'sha256':expected}
    marker=run([*flags,exact,'-c','from speaches.executors.parakeet import WIZARD_PINNED_PARAKEET; print(WIZARD_PINNED_PARAKEET)']);assert marker=='1'
    spec=importlib.util.spec_from_file_location('voice_security_closure',HERE/'security-closure.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    tls=subprocess.run([oci.DOCKER,'run','--pull=never','--rm','-i','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','/bin/sh',exact,'-s'],input=m.PROBE,text=True,capture_output=True,env=env,timeout=900)
    (root/'security.log').write_text(tls.stdout+tls.stderr);assert tls.returncode==0,'Inherited trust-client probes failed'
    row={**transport,'base':BASE,'key':'transcriber','predecessorSourceSha256':PREDECESSOR,
        'voiceSourceSha256':expected,'recipeSha256':sha(context/'Dockerfile'),
        'configPreserved':True,'baseLayersPreserved':True,'staleBytecodeRejected':True,
        'securityPassed':True,'securityLogSha256':sha(root/'security.log'),
        'voiceTranscriptionAccepted':False,'ownerActivation':False}
    # Receipt is only written after native import, identity and trust gates pass.
    (root/'result.json').write_text(json.dumps(row,indent=2)+'\n');print(json.dumps(row))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)

if __name__=='__main__':main()
