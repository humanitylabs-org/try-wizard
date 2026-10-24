#!/usr/bin/env python3
"""Build a code-only arm64 guest payload from already-pushed git archives.
Run inside the owned Linux QA guest, with archives extracted in --workspace.
"""
import argparse,hashlib,json,platform,shutil,subprocess,tempfile
from pathlib import Path
PINS={'ux':'31bdc3ecb0586f61323b72227ab70506d2627e5d','service':'77650c65f9c80b999ffd78ee58a23ecd99bdfbeb','wam':'0696805fe000dfc616abd0cf772c52ff83d580d9'}
BASE='sha256:b2f114e0520b4f210fd7e99dab08ccae44bb6bb47c870b00581f2cec30c24aca'
def run(args):return subprocess.check_output(list(map(str,args)),text=True).strip()
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--reuse-managed-from',type=Path,help='Preserve the authenticated prior managed archive for a Service-only release');a=p.parse_args();r=a.workspace
 assert platform.machine()=='aarch64','Build only in arm64 guest'
 pins=json.loads((r/'source-pins.json').read_text());assert all(pins[k]==v for k,v in PINS.items())
 assert run(['docker','image','inspect',BASE,'--format','{{.Id}}'])==BASE
 base_tag='wizard-shell:release-base-b2f114e0520b'
 subprocess.run(['docker','tag',BASE,base_tag],check=True)
 tag='wizard-shell:mac-release-'+pins['source'][:12]
 with tempfile.TemporaryDirectory(prefix='wizard-runtime-',dir='/var/lib/wizard') as d:
  b=Path(d)
  for source,dest in [(r/'service/server',b/'server'),(r/'ux/web',b/'ux')]:shutil.copytree(source,dest)
  for name in ['package.json','package-lock.json']:shutil.copy2(r/'service'/name,b/name)
  (b/'Dockerfile').write_text('FROM '+base_tag+'\nUSER root\nCOPY package*.json ./\nRUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force\nRUN rm -rf /app/server /app/ux\nCOPY server /app/server\nCOPY ux /app/ux\nLABEL org.opencontainers.image.revision="'+pins['service']+'" org.opencontainers.image.wizard-ux-revision="'+pins['ux']+'" org.opencontainers.image.wizard-guest-revision="'+pins['source']+'"\nUSER 1000:1000\n')
  subprocess.run(['docker','build','-t',tag,str(b)],check=True)
 subprocess.run(['docker','tag',tag,'wizard-shell:mac-mvp-20261013'],check=True)
 subprocess.run(['docker','save','-o',str(r/'wizard-shell.tar'),tag,'wizard-shell:mac-mvp-20261013'],check=True)
 if a.reuse_managed_from:
  prior=a.reuse_managed_from;previous=json.loads((prior/'runtime-bom.json').read_text())
  for key in ('ux','wam'):assert previous['sources'][key]==pins[key],key+' drift'
  managed=previous['managed_runtime']
  assert sha(prior/'wizard-hermes-managed.tar')==managed['sha256'],'Managed archive digest mismatch'
  manifest=json.loads((prior/'managed-runtime.json').read_text())
  assert manifest['image']==managed['image'] and manifest['stock']==managed['stock']
  for name in ('wizard-hermes-managed.tar','managed-runtime.json'):shutil.copy2(prior/name,r/name)
 else:
  managed_tag='wizard-hermes:managed-'+pins['source'][:12]
  subprocess.run(['docker','build','-t',managed_tag,str(r/'source/next/guest/managed-launch')],check=True)
  managed=json.loads(run(['docker','image','inspect',managed_tag]))[0]
  subprocess.run(['docker','save','-o',str(r/'wizard-hermes-managed.tar'),managed_tag],check=True)
  manifest={'image':managed['Id'],'stock':'f97608f178d1ffeca59860195ab7da295f7c8e5f'}
  (r/'managed-runtime.json').write_text(json.dumps(manifest,indent=2)+'\n')
 meta=json.loads(run(['docker','image','inspect',tag]))[0];assert meta['Architecture']=='arm64'
 bom={'schema':1,'sources':pins,'architecture':'arm64','service_image_id':meta['Id'],'service_tag':tag,'base_image_id':BASE,'payload_sha256':sha(r/'wizard-shell.tar'),'payload_bytes':(r/'wizard-shell.tar').stat().st_size,'recipe':'combined Service/UX compatibility package; exact split sources, existing Mac topology retained','stock_hermes':{'image_id':'sha256:666d6c659574fa09c1ea47b7ec5f03e8d2c35a8aa8055fe60c1e2fe3d3e03e9b','upstream_tag':'v2026.9.24','packaging_commit':'f97608f178d1ffeca59860195ab7da295f7c8e5f','upstream_commit_verified':False},'scope_gates':{'phone_enrollment':'not-activated-ingress-unaccepted','generic_builder':'separate-owner-not-in-this-freeze','optional_apps':'not-installed-no-new-licensing-approval','defleur':'amd64-only-not-arm64-ready'}}
 bom['optional_images']={'tinfoil_proxy':{'tag_inspected':'0.2.3','index_digest':'sha256:90584b70ed0636b08f6bee4657f947854b1dabe1842acbbcae8466019b559c9c','arm64_image':'ghcr.io/tinfoilsh/tinfoil-proxy@sha256:24edd55928bb9204c37bc6f48609de381d6513a4ce456c816394af307f02aa68','manifest_verified':True,'executed':False,'provider_key':'recipient-supplied-not-bundled'}}
 bom['managed_runtime']={**manifest,'archive':'wizard-hermes-managed.tar','sha256':sha(r/'wizard-hermes-managed.tar'),'bytes':(r/'wizard-hermes-managed.tar').stat().st_size}
 bom['files']={str(f.relative_to(r)):sha(f) for root in [r/'wam',r/'overlay',r/'agent-runtime',r/'source/next/guest'] for f in sorted(root.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
 bom['files']['managed-runtime.json']=sha(r/'managed-runtime.json')
 (r/'runtime-bom.json').write_text(json.dumps(bom,indent=2)+'\n');print(json.dumps(bom))
if __name__=='__main__':main()
