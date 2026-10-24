#!/usr/bin/env python3
"""Parent-only light job: activate this security preparation AFTER existing jobs 01-04 finish.
Never changes selected source archives/trees or accepts a new hash for an altered source.
"""
import argparse,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def emit(path,data):path.write_text(json.dumps(data,indent=2)+'\n')
def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',required=True,type=Path);a=p.parse_args();root=a.stage_root.resolve()
    assert sys.platform=='darwin' and root.is_relative_to(Path(os.environ['THALES_MEDIA']))
    overlay=root/'security-preparation-v1';manifest=json.loads((overlay/'overlay-manifest.json').read_text());prior=json.loads((root/'staged-files.json').read_text())
    # Previous image/source work is not duplicated or overwritten.
    pins=json.loads((root/'preparation/pins.json').read_text());source=json.loads((root/'source-checks-v5/result.json').read_text())
    assert source['passed'] is True and source['finalPins']==pins['finalPins']
    for key in ['wam','service','ux']:
        row=json.loads((root/'image-packaging'/key/'result.json').read_text());assert row['sourceCommit']==pins['finalPins'][key] and row['pullVerified'] is True
    incoming=json.loads((overlay/'pins.json').read_text());assert incoming['finalPins']==pins['finalPins'] and incoming['sourceInputs']==pins['sourceInputs']
    # Verify every original immutable staged path first. No global re-hash that launders source changes.
    for name,expected in prior['files'].items():assert sha(root/name)==expected,'staged input changed before security activation: '+name
    for name,target in prior.get('symlinks',{}).items():assert (root/name).is_symlink() and os.readlink(root/name)==target
    for name,expected in manifest['files'].items():assert sha(overlay/name)==expected,name
    backup=root/'preparation-before-security-v1';backup.mkdir(exist_ok=False)
    for name in manifest['files']:
        old=root/'preparation'/name
        if old.exists():shutil.copy2(old,backup/name)
        shutil.copy2(overlay/name,old);prior['files']['preparation/'+name]=manifest['files'][name]
    emit(root/'staged-files.json',prior)
    for name,expected in prior['files'].items():assert sha(root/name)==expected,name
    proc=subprocess.run([sys.executable,'-m','unittest','discover','-s','preparation','-p','test_*.py','-v'],cwd=root,text=True,capture_output=True,timeout=120)
    emit(root/'security-preparation-tests.json',{'passed':proc.returncode==0,'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'overlayManifestSha256':sha(overlay/'overlay-manifest.json'),'unitTestsNotAcceptance':True})
    assert proc.returncode==0,proc.stdout+proc.stderr
    audit=subprocess.run([sys.executable,'preparation/audit.py','--stage-root','.'],cwd=root,text=True,capture_output=True,timeout=120)
    assert audit.returncode==2,audit.stderr
    receipt=json.loads(audit.stdout);assert receipt['buildStarted'] is False
    emit(root/'security-admission-before-packaging.json',receipt)
    print(json.dumps({'activated':True,'files':len(manifest['files']),'unitTestsPassed':True,'finalPinsUnchanged':True,'buildStarted':False,'admission':receipt}))

if __name__=='__main__':main()
