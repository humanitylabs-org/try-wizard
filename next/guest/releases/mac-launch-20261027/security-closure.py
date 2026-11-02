#!/usr/bin/env python3
"""Fail-closed eMudhra closure: CA bundles, certifi and Node; network failure is not rejection.
Standalone preflight needs a complete immutable image plan; missing inherited image coverage blocks.
"""
import argparse, json, os, re, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
BAD=['dv-g3b-emudhra','dv-g3b-aaa-emudhra','dv-g3b-noct-emudhra','dv-g3b-aaa-noct-emudhra']
GOOD='https://example.com/'

# Runs in the target process/rootfs, never trusts the host's store as image evidence.
PROBE=r'''set -eu
command -v curl >/dev/null
curl -fsS --max-time 20 https://example.com/ >/dev/null
for h in dv-g3b-emudhra dv-g3b-aaa-emudhra dv-g3b-noct-emudhra dv-g3b-aaa-noct-emudhra; do
 rc=0; curl -fsS --max-time 20 https://$h.we-have-a-problem.com/ >/dev/null || rc=$?
 test "$rc" = 60 || exit 41
done
if command -v node >/dev/null; then
 node -e 'let v=process.versions.node.split(".").map(Number);if(v[0]<22||(v[0]===22&&(v[1]<23||(v[1]===23&&v[2]<4))))process.exit(42)'
 node -e 'const h=require("https");h.get("https://example.com/",r=>{r.resume();if(r.statusCode!==200)process.exit(43)}).on("error",()=>process.exit(44))'
 for h in dv-g3b-emudhra dv-g3b-aaa-emudhra; do
 node -e 'const h=require("https");let r=h.get(process.argv[1],()=>process.exit(45));r.setTimeout(20000,()=>process.exit(46));r.on("error",e=>{if(!/CERT|ISSUER|VERIFY|SELF_SIGNED/.test(e.code||""))process.exit(47)})' https://$h.we-have-a-problem.com/
 done
fi
if command -v python3 >/dev/null; then
 python3 - <<'PY'
import ssl,urllib.request,urllib.error,pathlib
bad=['dv-g3b-emudhra','dv-g3b-aaa-emudhra']
contexts=[ssl.create_default_context()]
try:
 import certifi
 assert tuple(map(int,certifi.__version__.split('.'))) >= (2026,10,19)
 contexts.append(ssl.create_default_context(cafile=certifi.where()))
except ImportError:pass
# Vendored and venv copies must be checked too, not just the first import on sys.path.
for root in ['/opt','/app','/usr/local/lib','/home/wizard','/root']:
 for bundle in pathlib.Path(root).glob('**/certifi/cacert.pem'):
  contexts.append(ssl.create_default_context(cafile=str(bundle)))
for ctx in contexts:
 urllib.request.urlopen('https://example.com/',context=ctx,timeout=20).close()
 for h in bad:
  try:urllib.request.urlopen('https://'+h+'.we-have-a-problem.com/',context=ctx,timeout=20)
  except urllib.error.URLError as e:
   assert isinstance(e.reason,ssl.SSLCertVerificationError),str(e)
  else:raise AssertionError('compromised chain accepted')
print('Python system and all discovered certifi contexts reject compromised chains')
PY
fi
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',type=Path);p.add_argument('--guest',action='store_true');p.add_argument('--output',type=Path);a=p.parse_args()
    docker='docker' if a.guest else '/opt/homebrew/bin/docker';plan={}
    if not a.guest:
        assert a.stage_root and sys.platform=='darwin'
        plan=json.loads((HERE/'security-image-plan.json').read_text())
        if plan.get('complete') is not True:raise SystemExit('SECURITY_IMAGE_CLOSURE: inherited/default image inventory and remediation pins remain incomplete; never defer queue 81')
        images=plan['images'];root=a.stage_root
    else:
        ids=subprocess.check_output([docker,'ps','-q'],text=True).split()
        assert ids,'no guest containers to verify'
        rows=json.loads(subprocess.check_output([docker,'inspect',*ids],text=True));images=sorted({c['Image'] for c in rows});root=Path('/mnt/launch')
        # Test every running container's actual environment and bind-mounted trust stores, not fresh image defaults.
        running=[(c['Id'],c['Image']) for c in rows]
    output=a.output or root/'security-preflight.json';result={'passed':False,'images':images,'checks':[],'allGuestImagesEnumerated':bool(a.guest),'publishing':False}
    if a.guest:
        host=subprocess.run(['sh','-s'],input=PROBE,text=True,capture_output=True,timeout=240)
        result['checks'].append({'target':'guest-host','returncode':host.returncode,'log':host.stdout+host.stderr})
    for identity,image in (running if a.guest else [(image,image) for image in images]):
        if not a.guest:assert re.fullmatch(r'.+@sha256:[0-9a-f]{64}',image),'immutable manifest required'
        argv=([docker,'exec','-i','-e','PYTHONDONTWRITEBYTECODE=1',identity,'/bin/sh','-s'] if a.guest else [docker,'run','--rm','-i','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','/bin/sh',image,'-s'])
        proc=subprocess.run(argv,input=PROBE,text=True,capture_output=True,timeout=240)
        result['checks'].append({'target':image,'container':identity if a.guest else None,'returncode':proc.returncode,'log':proc.stdout+proc.stderr})
    result['passed']=bool(result['checks']) and all(x['returncode']==0 for x in result['checks'])
    # preflight inventory is complete only when every explicitly enumerated selected/default/inherited image was tested.
    if not a.guest:result['allGuestImagesEnumerated']=plan['complete']
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'receipt':str(output)}));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
