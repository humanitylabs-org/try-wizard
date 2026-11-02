#!/usr/bin/env python3
"""Durable Thales-only build307 + focused native/legacy acceptance entrypoint.
No factory build, publication, feed writes, or private305 path. Source must have
been pushed and staged at the exact immutable revision in the supplied spec.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import plistlib
import shutil
import subprocess
import sys

WORK_ROOT = Path(os.environ.get("WIZARD_WORK_ROOT") or Path(os.environ.get("TMPDIR") or "/tmp") / "wizard-work").expanduser().resolve()
WORK_ROOT.mkdir(parents=True, exist_ok=True)


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True); a=parser.parse_args()
    spec=json.loads(a.spec.read_text()); root=Path(spec['evidenceRoot'])
    source=Path(__file__).resolve().parents[3]
    assert os.uname().sysname=='Darwin'
    assert source.is_relative_to(WORK_ROOT) and root.is_relative_to(WORK_ROOT)
    assert not root.exists(), 'Immutable evidence directory only'
    assert subprocess.check_output(['git','-C',source,'rev-parse','HEAD'],text=True).strip()==spec['source']
    assert not subprocess.check_output(['git','-C',source,'status','--porcelain'],text=True).strip()
    # The durable worker is the only owner of the shared resource lease. No
    # nested flock or detached VM/background worker is created here.
    root.mkdir(parents=True,mode=0o700)
    (WORK_ROOT / 'tmp').mkdir(parents=True, exist_ok=True)
    env=dict(os.environ,PATH='/opt/homebrew/bin:'+os.environ['PATH'],TMPDIR=str(WORK_ROOT / 'tmp'),PYTHONDONTWRITEBYTECODE='1',UV_CACHE_DIR=str(WORK_ROOT / 'tmp/uv-cold-cache'),UV_PYTHON_INSTALL_DIR=str(WORK_ROOT / 'tmp/uv-cold-python'))
    result={'schema':1,'source':spec['source'],'build':'307','phase':'focused-checks','upgradeAccepted':False,
            'factoryRebuilt':False,'published':False,'checks':[],'baselineUntouched':None,
            'remainingAcceptance':['actual VM post-apply rollback','active capture/foreign Host refusal UI','physical microphone speech','meeting upload']}
    def save(): (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    def check(name,argv,timeout=180):
        with (root/(name+'.log')).open('w') as out:
            child=subprocess.Popen(list(map(str,argv)),env=env,stdout=out,stderr=subprocess.STDOUT)
            try: rc=child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.terminate(); rc=child.wait(timeout=240)
                result['timedOut']=name
        result['checks'].append({'name':name,'exitCode':rc,'logSHA256':sha(root/(name+'.log'))});save()
        if rc or result.get('timedOut')==name: raise RuntimeError(name+' failed')
    save()
    try:
        check('qa-venv',[spec['uv'],'venv','--python',spec['python'],root/'venv'])
        python=str(root/'venv/bin/python')
        check('qa-deps',[spec['uv'],'pip','install','--python',python,'PyYAML==6.0.3','Pillow==12.0.0'])
        env['PATH']=str(root/'venv/bin')+':'+env['PATH']
        check('guest-policy', [python,source/'next/guest/tests/test_cold_bootstrap.py'])
        mac=source/'next/mac'
        check('process-identity', [python,mac/'Tests/test_legacy_process_identity.py'])
        check('compile-admission',['xcrun','swiftc','-swift-version','5','-target','arm64-apple-macos14.0',mac/'Shared/UpdateContract.swift',mac/'Tests/LegacyAdmission/main.swift','-o',root/'admission'])
        check('admission',[root/'admission',root/'admission-data'])
        check('compile-activation',['xcrun','swiftc','-swift-version','5','-target','arm64-apple-macos14.0',mac/'Shared/DiskIdentity.swift',mac/'App/WizardGuestActivation.swift',mac/'Tests/GuestActivation/main.swift','-framework','AppKit','-o',root/'activation'])
        check('activation',[root/'activation',root/'activation-data'])
        payload=root/'payload'
        check('clone-sealed-payload',['cp','-cR',spec['frozenPayload'],payload])
        frozen=Path(spec['frozenPayload']); bom=json.loads((payload/'runtime-bom.json').read_text())
        # Only bounded migration source changes; both large image archives stay byte-identical.
        for name in ('wizard-shell.tar','wizard-hermes-managed.tar'):
            assert sha(payload/name)==sha(frozen/name)
        for name in ('upgrade-mvp-stack.py','cold-bootstrap.py','cold-config.py'):
            relative='source/next/guest/'+name; target=payload/relative
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/'next/guest'/name,target)
            bom['files'][relative]=sha(target)
        bom['sources']['COLD_BOOTSTRAP']=spec['source']
        (payload/'runtime-bom.json').write_text(json.dumps(bom,sort_keys=True)+'\n')
        public=plistlib.loads((Path(spec['publicApp'])/'Contents/Info.plist').read_bytes())['SUPublicEDKey']
        env.update(VER='0.7.0',BUILD='307',SPARKLE_DIR=spec['sparkle'],SPARKLE_PUBLIC_KEY=public,
                   SPARKLE_FEED='https://downloads.aiwizards.com/mac/appcast.xml',GUEST_UPDATE_PAYLOAD=str(payload),
                   RELEASE_ID=spec['source'],SIGN_IDENTITY='-',DMG='0')
        check('native307-build',['bash',mac/'build.sh'],1200)
        app=Path(spec['candidateApp']); assert app.parent==Path('/Applications') and not app.exists()
        check('install-owned-candidate',['cp','-cR',mac/'dist/Wizard.app',app],120)
        result['candidateApp']=str(app);result['phase']='candidate-built';save()
        check('legacy061-candidate',[spec['python'],mac/'Tests/legacy061_probe.py','--root',root/'vm',
              '--baseline-disk',spec['baselineDisk'],'--boot-dir',spec['bootDir'],
              '--old-app',spec['oldApp'],'--old-launch-app',spec['oldLaunchApp'],
              '--new-app',app,'--quit-helper',spec['quitHelper'],'--worker-lease','inherited',
              '--candidate-source',spec['source']],2400)
        vm=json.loads((root/'vm/result.json').read_text())
        result['baselineUntouched']=vm['originalBaselineUnchanged']
        result['candidateTested']=vm.get('candidateTested',False)
        result['coldWitness']=vm.get('coldWitness')
        result['successPathAccepted']=vm.get('successPathAccepted',False)
        result['repeatLaunchNoOp']=vm.get('repeatLaunchNoOp',False)
        result['phase']='focused-candidate-checks-complete'
        # Remaining matrix deliberately prevents a build/success path from becoming
        # release acceptance. Parent owns that tail and eventual publication.
    except BaseException as e:
        result['phase']='failed';result['error']=type(e).__name__+': '+str(e);raise
    finally: save()
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
