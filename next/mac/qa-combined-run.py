#!/usr/bin/env python3
"""Bounded exact-DMG test continuation; caller owns shared keep-file lock."""
import datetime, hashlib, json, os, pathlib, plistlib, signal, subprocess, time
R=pathlib.Path('/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-fix-round-20261014/compose')
S=R/'source-smoke-r1';Q=pathlib.Path(os.environ.get('COMBINED_QA_ROOT',str(R/'native-qa-r1')));E=Q/'evidence';E.mkdir(parents=True,exist_ok=True)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
receipt={'started':now(),'state':'running','sourceSnapshot':str(S),'tests':{}}
(E/'acquired.txt').write_text(now())
def run(argv, logfile, timeout=360):
    with (E/logfile).open('w') as log:
        p=subprocess.Popen(list(map(str,argv)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            return 124
mount=Q/'mount';mount.mkdir(exist_ok=True)
mounted=False
try:
    assert (S/'evidence/result.txt').read_text().strip()=='COMPOSED_SOURCE_SMOKE_PASS','Source smoke did not pass; no native test launched'
    dmg=S/'source/next/mac/dist/Wizard-0.6.2.dmg'
    receipt['dmg']=str(dmg);receipt['dmgSHA256']=hashlib.sha256(dmg.read_bytes()).hexdigest()
    # Recover only this lane's exact prior failed-harness mount, under owning lock.
    old=R/'native-qa-r1/mount'
    images=plistlib.loads(subprocess.check_output(['hdiutil','info','-plist']))['images']
    for image in images:
        if any(entity.get('mount-point')==str(old) for entity in image.get('system-entities',[])):
            assert pathlib.Path(image['image-path']).resolve()==dmg.resolve(),'Foreign prior mount; preserve it'
            receipt['priorHarnessMountDetachExit']=run(['hdiutil','detach',old],'prior-mount-detach.log',90)
            assert receipt['priorHarnessMountDetachExit']==0,'Owned prior mount cleanup failed'
    assert run(['hdiutil','verify',dmg],'dmg-verify.log',120)==0,'DMG verify failed'
    assert run(['hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,dmg],'mount.log',120)==0,'Readonly mount failed'
    mounted=True
    apps=[p for p in mount.glob('*.app') if plistlib.loads((p/'Contents/Info.plist').read_bytes()).get('CFBundleIdentifier')=='org.humanitylabs.wizard.mvp']
    assert len(apps)==1,'DMG must contain exactly one MVP app'
    app=apps[0];receipt['mountedApp']=str(app)
    receipt['binarySHA256']=hashlib.sha256((app/'Contents/MacOS/Wizard').read_bytes()).hexdigest()
    assert run(['codesign','--verify','--strict','--deep',app],'codesign.log',60)==0,'Mounted codesign failed'
    tests=[('drag-authority',S/'source/next/mac/qa-native-drag-authority.py'),('desktop',Q/'qa-combined-desktop.py'),('voice',S/'source/next/mac/qa-native-voice-authority.py')]
    for name,script in tests:
        rc=run(['/opt/homebrew/bin/python3',script,app,S/'ux/web',E/name],name+'.log',420)
        receipt['tests'][name]={'exit':rc,'evidence':str(E/name),'scriptSHA256':hashlib.sha256(script.read_bytes()).hexdigest()}
        (E/'job.json').write_text(json.dumps(receipt,indent=2))
        # Every independently bounded component is exercised, without hiding earlier failures.
    receipt['state']='passed' if all(v['exit']==0 for v in receipt['tests'].values()) else 'failed'
except Exception as exc:receipt.update(state='failed',error=str(exc))
finally:
    if mounted:
        receipt['unmountExit']=run(['hdiutil','detach',mount],'unmount.log',90)
        if receipt['unmountExit']!=0:receipt.update(state='failed',cleanupError='Owned DMG unmount failed')
    receipt['finished']=now();(E/'job.json').write_text(json.dumps(receipt,indent=2))
    (E/'exit.txt').write_text('EXIT '+('0' if receipt['state']=='passed' else '1')+' '+now())
print(json.dumps(receipt,indent=2),flush=True)
raise SystemExit(0 if receipt['state']=='passed' else 1)
