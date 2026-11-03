#!/usr/bin/env python3
"""Resolve only REAL secured voice output into a fresh candidate payload/plan.
Never mutates the retained predecessor stage, publishes, or invents an image ID.
"""
import argparse, hashlib, importlib.util, json, shutil
from pathlib import Path
import local_oci as oci
HERE=Path(__file__).resolve().parent

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);assert s and s.loader
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def resolve(receipt, native, output, plan_path=None):
    row=json.loads(receipt.read_text());package=receipt.parent
    assert row['securityPassed'] is True and row['configPreserved'] is True and row['baseLayersPreserved'] is True and row['staleBytecodeRejected'] is True
    assert row['base']==load('package_voice',HERE/'package-voice-image.py').BASE
    archive=oci.validate(package,row)
    assert oci.verify_archive(archive)['manifestDigest']==row['manifestDigest']
    m=load('resolved_voice_reconcile',native/'overlay/opt/wizard/voice/reconcile.py')
    old=m.validate_selection(json.loads((native/'releases/mac-launch-20261027/voice-selected-engine.json').read_text()))
    assert old['image']==row['base']
    selected=json.loads(json.dumps(old));selected['image']=row['ref']+'@'+row['digest'];selected['bindings']['transcriber-engine']=selected['image'];m.validate_selection(selected)
    output.mkdir(parents=True,exist_ok=False)
    # Minimal normal component payload; full stack sealer consumes these exact
    # generated members when assembling a wider authenticated runtime BOM.
    installer=load('resolved_voice_install',native/'overlay/opt/wizard/voice/install.py')
    for rel in installer.FILES:
        p=output/'overlay'/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(native/'overlay'/rel,p)
    shutil.copy2(archive,output/'voice-engine.oci.tar')
    raw=(json.dumps(selected,indent=2,sort_keys=True)+'\n').encode();(output/'selected-engine.json').write_bytes(raw)
    d={'schema':1,'selection':selected,'previousSelection':old,'archive':'voice-engine.oci.tar',
       'archiveSha256':row['archiveSha256'],'imageId':row['imageId'],
       'securityPassed':True,'configPreserved':True,'baseLayersPreserved':True,
       'sourceReceiptSha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
    (output/'voice-package.json').write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
    if plan_path:
        plan=json.loads(plan_path.read_text());assert plan['resolutions']['transcriber']['image']==old['image']
        target=next(t for t in plan['targets'] if t['key']=='transcriber');target.update(base=row['base'],receipt=str(receipt),voiceOverlay=True)
        plan['resolutions']['transcriber'].update(image=selected['image'],imageId=row['imageId'],receipt=str(receipt),receiptSha256=d['sourceReceiptSha256'])
        plan['images']=sorted(selected['image'] if v==old['image'] else v for v in plan['images'])
        plan.update(complete=False,status='voice-derived-awaiting-final-security-closure')
        (output/'security-image-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    inventory={str(p.relative_to(output)):oci.sha(p) for p in output.rglob('*') if p.is_file()}
    (output/'resolved-files.json').write_text(json.dumps(inventory,indent=2,sort_keys=True)+'\n')
    return d

def main():
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--native',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--security-plan',type=Path)
    a=p.parse_args();print(json.dumps(resolve(a.receipt,a.native,a.output,a.security_plan)))

if __name__=='__main__':main()
