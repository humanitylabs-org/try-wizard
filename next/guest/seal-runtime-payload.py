#!/usr/bin/env python3
"""Seal a code-only payload on Thales after runtime verification; no user state."""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);a=p.parse_args();r=a.workspace
pins=json.loads((r/'source-pins.json').read_text());bom=json.loads((r/'runtime-bom.json').read_text());up=json.loads((r/'hermes-source-verification.json').read_text())
assert up['verified'] and not up['changed'],'Upstream source parity required'
assert pins==bom['sources'],'Source pins changed since image build'
dst=r/'payloads'/pins['source'][:12];dst.mkdir(parents=True,exist_ok=False)
for name,src in [('wam',r/'wam'),('overlay',r/'source/next/guest/overlay'),('agent-runtime',r/'service/ops/agent-runtime')]:
 shutil.copytree(src,dst/name,ignore=shutil.ignore_patterns('.git','__pycache__','.pytest_cache','node_modules'))
for name in ['upgrade-mvp-stack.py','stack-preservation.py','test-stack-preservation.py']:
 d=dst/'source/next/guest'/name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(r/'source/next/guest'/name,d)
shutil.copy2(r/'wizard-shell.tar',dst/'wizard-shell.tar')
if bom.get('managed_runtime'):
 for name in ['wizard-hermes-managed.tar','managed-runtime.json']:shutil.copy2(r/name,dst/name)
bom['stock_hermes'].update(upstream_commit=up['upstream']['upstream_commit'],upstream_repository=up['upstream']['repository'],upstream_commit_verified=True,verified_runtime_python_files=up['runtime_python_files'],matching_upstream_python_files=up['matching_files'],changed_upstream_python_files=up['changed'])
bom['stock_hermes'].pop('packaging_commit',None)
bom['stock_hermes']['packaging_label_revision']='f97608f178d1ffeca59860195ab7da295f7c8e5f'
def sha(f):
 with f.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
bom['files']={str(f.relative_to(dst)):sha(f) for f in sorted(dst.rglob('*')) if f.is_file()}
(dst/'runtime-bom.json').write_text(json.dumps(bom,indent=2)+'\n')
archive=r/('wizard-guest-software-'+pins['source'][:12]+'.tar.gz')
subprocess.run(['tar','-czf',str(archive),'-C',str(dst),'.'],check=True)
receipt={'payload_directory':str(dst),'archive':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,'source':pins['source'],'service_image_id':bom['service_image_id'],'bom_sha256':sha(dst/'runtime-bom.json')}
(r/'payload-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
