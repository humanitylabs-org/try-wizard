#!/usr/bin/env python3
"""Build a code-only arm64 guest payload from already-pushed git archives.
Run inside the owned Linux QA guest, with archives extracted in --workspace.
"""
import argparse,hashlib,json,platform,shutil,subprocess,tempfile
from pathlib import Path
PINS={'ux':'eee6e3fba678c734be0322645b90c2691ee4ff35','service':'714b8201550c360d96fcb3b77b6b559625d2fa1b','wam':'56edd6853716510e6b36b338da42ad95615212ac'}
BASE='sha256:b2f114e0520b4f210fd7e99dab08ccae44bb6bb47c870b00581f2cec30c24aca'
def run(args):return subprocess.check_output(list(map(str,args)),text=True).strip()
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);a=p.parse_args();r=a.workspace
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
 meta=json.loads(run(['docker','image','inspect',tag]))[0];assert meta['Architecture']=='arm64'
 bom={'schema':1,'sources':pins,'architecture':'arm64','service_image_id':meta['Id'],'service_tag':tag,'base_image_id':BASE,'payload_sha256':sha(r/'wizard-shell.tar'),'payload_bytes':(r/'wizard-shell.tar').stat().st_size,'recipe':'combined Service/UX compatibility package; exact split sources, existing Mac topology retained','stock_hermes':{'image_id':'sha256:666d6c659574fa09c1ea47b7ec5f03e8d2c35a8aa8055fe60c1e2fe3d3e03e9b','upstream_tag':'v2026.9.24','packaging_commit':'f97608f178d1ffeca59860195ab7da295f7c8e5f','upstream_commit_verified':False},'scope_gates':{'phone_enrollment':'not-activated-ingress-unaccepted','generic_builder':'separate-owner-not-in-this-freeze','optional_apps':'not-installed-no-new-licensing-approval','defleur':'amd64-only-not-arm64-ready'}}
 bom['files']={str(f.relative_to(r)):sha(f) for root in [r/'wam',r/'overlay',r/'agent-runtime',r/'source/next/guest'] for f in sorted(root.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
 (r/'runtime-bom.json').write_text(json.dumps(bom,indent=2)+'\n');print(json.dumps(bom))
if __name__=='__main__':main()
