#!/usr/bin/env python3
"""Parent-only: adopt REAL image outputs into pins/RC; preserve pre-resolution input.
No image build, VM, git tag, feed, release publication or fabricated digest.
"""
import argparse, hashlib, json, os, re
from pathlib import Path
import local_oci as oci

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',required=True,type=Path);a=p.parse_args();root=a.stage_root.resolve();prep=root/'preparation'
    assert root.is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media')))
    pins=json.loads((prep/'pins.json').read_text());rc=json.loads((prep/'wizard-os-release-candidate.json').read_text());images={}
    source=json.loads((root/'source-checks-v5/result.json').read_text());assert source['passed'] is True and source['finalPins']==pins['finalPins']
    for key,name in [('wam','wizard-app-manager'),('service','wizard-agent-service'),('ux','wizard-ux')]:
        row=json.loads((root/'image-packaging'/key/'result.json').read_text())
        assert row['sourceCommit']==pins['finalPins'][key] and row['loadVerified'] is True and row['tagsPublished'] is False
        assert re.fullmatch(r'sha256:[0-9a-f]{64}',row['digest']) and row['ref']=='ghcr.io/humanitylabs-org/'+name
        oci.validate(root,row)
        pins['assembly']['images'][key]['digest']=row['digest'];images[name]={'ref':row['ref'],'digest':row['digest'],'source_commit':row['sourceCommit']}
    # A built core image alone is not evidence that inherited/default runtime images are remediated.
    plan=json.loads((prep/'security-image-plan.json').read_text());security=json.loads((root/'security-preflight.json').read_text())
    assert plan['complete'] is True and security['passed'] is True and security['allGuestImagesEnumerated'] is True
    assert set(security['images'])==set(plan['images']) and images
    # Do not launder altered immutable staged sources by simply rehashing them.
    prior=json.loads((root/'staged-files.json').read_text())
    mutable={'preparation/pins.json','preparation/wizard-os-release-candidate.json','preparation/security-image-plan.json'}
    for name,expected in prior['files'].items():
        assert name in mutable or sha(root/name)==expected, 'immutable staged input changed: '+name
    assert plan.get('images') and set(plan['images'])==set(security['images'])
    before=root/'selection-before-image-resolution';before.mkdir(exist_ok=False)
    for name in ['pins.json','wizard-os-release-candidate.json','staged-files.json']:
        src=root/name if name=='staged-files.json' else prep/name
        (before/name).write_bytes(src.read_bytes())
    import importlib.util
    spec=importlib.util.spec_from_file_location('security_closure',prep/'security-closure.py');assert spec and spec.loader
    closure=importlib.util.module_from_spec(spec);spec.loader.exec_module(closure)
    actual,resolutions=closure.resolve_plan(plan,root,pins)
    assert actual==plan['images'] and resolutions==plan['resolutions']
    assert security.get('schema')==2 and security.get('planSha256')==sha(prep/'security-image-plan.json')
    images=closure.security_release_images(plan,images)
    rc['images']=images;rc['status']='factory-bootstrap-ready'
    rc['hermes']['image']={'ref':plan['resolutions']['stock']['image'].split('@')[0],'digest':plan['resolutions']['stock']['image'].split('@')[1]}
    rc['default_apps']['recorder']['image']=plan['resolutions']['recorder']['image']
    pins['recorderImage']['upstreamArm64Image']=pins['recorderImage'].get('upstreamArm64Image',pins['recorderImage']['arm64Image'])
    pins['recorderImage']['arm64Image']=rc['default_apps']['recorder']['image']
    pins['runtimeBuild']['hermesImage']=plan['resolutions']['stock']['image']
    pins['runtimeBuild']['baseStatus']='all selected image trust clients verified by security-preflight.json; guest host/runtime repeat mandatory'
    runtime={k:rc[k] for k in ['version','components','default_apps','hermes','images']}
    (root/'runtime-release.json').write_text(json.dumps(runtime,indent=2)+'\n')
    (prep/'wizard-os-release-candidate.json').write_text(json.dumps(rc,indent=2)+'\n')
    pins['wizardOsCandidate']['sha256']=sha(prep/'wizard-os-release-candidate.json');pins['status']='execution-inputs-resolved-awaiting-audit'
    (prep/'pins.json').write_text(json.dumps(pins,indent=2)+'\n')
    # Re-hash each original inventory target, plus explicit generated manifest and security plan. No test scratch.
    inventory=json.loads((root/'staged-files.json').read_text())
    for name in inventory['files']:inventory['files'][name]=sha(root/name)
    for name in ['runtime-release.json','preparation/security-image-plan.json']:inventory['files'][name]=sha(root/name)
    (root/'staged-files.json').write_text(json.dumps(inventory,indent=2)+'\n')
    # Read exact bytes back and bind pre/post resolution in a receipt; parent commits these pins on its named branch.
    assert json.loads((prep/'pins.json').read_text())['assembly']['images']==pins['assembly']['images']
    receipt={'pinsSha256':sha(prep/'pins.json'),'runtimeReleaseSha256':sha(root/'runtime-release.json'),'preResolutionPinsSha256':sha(before/'pins.json'),'images':images,'publishing':False}
    (root/'image-resolution.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
