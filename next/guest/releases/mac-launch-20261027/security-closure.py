#!/usr/bin/env python3
"""Fail-closed eMudhra closure over real outputs; discovery is not acceptance.
05 resolves actual immutable packaging receipts and tests every selected image.
The final guest repeats this for host and each running container's real environment.
"""
import argparse, concurrent.futures, hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path
import local_oci as oci
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('security_probe',HERE/'security-probe.py');assert spec and spec.loader
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
BAD=probe.BAD;GOOD=probe.GOOD

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(argv,**kw):return subprocess.check_output(argv,text=True,timeout=kw.pop('timeout',120),**kw)
def resolve_plan(plan,root,pins):
    assert plan.get('schema')==2 and plan.get('selectionComplete') is True
    assert len(plan['targets'])==17 and len({r['key'] for r in plan['targets']})==17
    images=[];resolutions={}
    for target in plan['targets']:
        row=json.loads((root/target['receipt']).read_text());assert row['loadVerified'] is True and row['tagsPublished'] is False
        oci.validate(root,row)
        assert re.fullmatch(r'sha256:[0-9a-f]{64}',row['digest'])
        if target['resolution']=='derive-image':
            assert row['key']==target['key'] and row['base']==target['base']
            assert row['ref']=='ghcr.io/humanitylabs-org/wizard-mac-security-'+target['key']
        else:
            assert target['resolution']=='selected-core-image' and row['sourceCommit']==pins['finalPins'][target['key']]
            assert row['ref']=='ghcr.io/humanitylabs-org/'+{'wam':'wizard-app-manager','service':'wizard-agent-service','ux':'wizard-ux'}[target['key']]
        image=row['ref']+'@'+row['digest'];images.append(image);resolutions[target['key']]={'image':image,'receipt':target['receipt'],'receiptSha256':sha(root/target['receipt']),'imageId':row['imageId']}
    assert len(set(images))==len(images)
    return sorted(images),resolutions

def security_release_images(plan, images):
    # Primary engine pins are supported by WAM release_pins.resolve; helpers/infra use persistent overrides.
    apps={'hermes-app':'hermes-agent','chatgpt':'wizard-chatgpt','claude':'wizard-claude','files':'files','transcriber':'transcriber','browser':'browser','secrets':'secret-drop','notifications':'notifications','recorder':'wizard-recorder'}
    result=dict(images)
    for key,app in apps.items():
        image=plan['resolutions'][key]['image'];ref,digest=image.split('@')
        result[app]={'ref':ref,'digest':digest,'security_target':key}
    return result

def probe_shell():
    hosts=' '.join(BAD)
    source=(HERE/'security-probe.py').read_text()
    return r'''set -eu
command -v curl >/dev/null
curl -fsS --max-time 20 https://example.com/ >/dev/null
curl -fsS --max-time 20 https://probe-emudhra.we-have-a-problem.com/ | grep -q 'Your client successfully connected to the site.'
for h in HOSTS; do
 rc=0; curl -fsS --max-time 20 https://$h.we-have-a-problem.com/ >/dev/null || rc=$?
 test "$rc" = 60 || exit 41
done
if command -v node >/dev/null; then
 node -e 'const v=process.versions.node.split(".").map(Number),m={22:[22,23,4],24:[24,22,1],26:[26,12,1]},x=m[v[0]];if(!x||v[1]<x[1]||(v[1]===x[1]&&v[2]<x[2]))process.exit(42)'
 for h in example.com probe-emudhra.we-have-a-problem.com; do
 node -e 'const h=require("https");let r=h.get("https://"+process.argv[1]+"/",r=>{r.resume();if(r.statusCode!==200)process.exit(43)});r.setTimeout(20000,()=>process.exit(46));r.on("error",()=>process.exit(44))' $h
 done
 for h in HOSTS; do
 node -e 'const h=require("https");let r=h.get(process.argv[1],()=>process.exit(45));r.setTimeout(20000,()=>process.exit(46));r.on("error",e=>{if(!/^(CERT_|UNABLE_TO_|SELF_SIGNED_|DEPTH_ZERO_SELF_SIGNED_CERT|ERR_TLS_CERT_ALTNAME_INVALID)/.test(e.code||""))process.exit(47)})' https://$h.we-have-a-problem.com/
 done
fi
# Native vendored roots need their own patched binaries; an OS store bump is not sufficient.
for c in uv uvx; do
 if command -v "$c" >/dev/null; then "$c" --version | grep -Eq '^(uv|uvx) 0\.(13\.[5-9]|1[4-9]\.|[2-9][0-9]\.)'; fi
done
if command -v claude >/dev/null; then claude --version | grep -Eq '^2\.1\.(30[3-9]|3[1-9][0-9]|[4-9][0-9][0-9]) '; fi
if command -v bun >/dev/null; then bun --version | grep -Eq '^1\.([4-9]\.[4-9]|[5-9]\.)'; fi
# Every distinct shipped interpreter, not only python3's PATH alias.
seen=' '
for p in /usr/bin/python3 /usr/local/bin/python3 /opt/hermes/.venv/bin/python /opt/uv-python/*/bin/python3 /opt/wizard-security-python/*/bin/python3; do
 test -x "$p" || continue
 real=$(readlink -f "$p")
 case "$seen" in *" $real "*) continue;; esac
 seen="$seen$real "
 "$p" - <<'WIZARD_SECURITY_PY'
PY_SOURCE
WIZARD_SECURITY_PY
done
'''.replace('HOSTS',hosts).replace('PY_SOURCE',source)

# Kept for source contract tests and external inspection; executes no commands on import.
PROBE=probe_shell()

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',type=Path);p.add_argument('--guest',action='store_true');p.add_argument('--output',type=Path);a=p.parse_args()
    docker='docker' if a.guest else '/opt/homebrew/bin/docker';plan={};env=os.environ.copy()
    if not a.guest:
        assert a.stage_root and sys.platform=='darwin';root=a.stage_root.resolve()
        plan=json.loads((HERE/'security-image-plan.json').read_text());pins=json.loads((HERE/'pins.json').read_text())
        images,resolutions=resolve_plan(plan,root,pins)
        env=oci.environment(root/'security-packaging')
        for target in plan['targets']:
            row=json.loads((root/target['receipt']).read_text());oci.load(root,row,docker,env)
        running=[(image,image) for image in images]
    else:
        root=Path('/mnt/launch');ids=run([docker,'ps','-q']).split();assert ids
        rows=json.loads(run([docker,'inspect',*ids]));running=[(c['Id'],c['Image']) for c in rows];images=sorted({c['Image'] for c in rows});resolutions={}
        # Private-account content is never an admissible factory source.
        assert not any('private' in c['Name'] for c in rows),'private container refused'
    output=a.output or root/'security-preflight.json'
    result={'schema':2,'passed':False,'images':images,'checks':[],'allGuestImagesEnumerated':False,'publishing':False,'resolutions':resolutions}
    if a.guest:
        host=subprocess.run(['sh','-s'],input=PROBE,text=True,capture_output=True,timeout=1200)
        result['checks'].append({'target':'guest-host','returncode':host.returncode,'log':host.stdout+host.stderr})
    def check(row):
        identity,image=row
        argv=([docker,'exec','-i','-e','PYTHONDONTWRITEBYTECODE=1',identity,'/bin/sh','-s'] if a.guest else [docker,'run','--pull=never','--rm','-i','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','/bin/sh',image,'-s'])
        try:
            proc=subprocess.run(argv,input=PROBE,text=True,capture_output=True,timeout=1200,env=env)
            return {'target':image,'container':identity if a.guest else None,'returncode':proc.returncode,'log':proc.stdout+proc.stderr}
        except subprocess.TimeoutExpired:return {'target':image,'container':identity if a.guest else None,'returncode':124,'log':'inconclusive: timeout, never counted as certificate rejection'}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:result['checks']+=list(pool.map(check,running))
    result['passed']=bool(result['checks']) and all(x['returncode']==0 for x in result['checks'])
    result['allGuestImagesEnumerated']=result['passed'] and (a.guest or len(images)==len(plan['targets']))
    if not a.guest and result['passed']:
        plan.update(complete=True,status='all-selected-images-probed',images=images,resolutions=resolutions)
        (HERE/'security-image-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
        result['planSha256']=sha(HERE/'security-image-plan.json')
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'receipt':str(output),'imageCount':len(images)}));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
