#!/usr/bin/env python3
"""Fail-closed eMudhra closure over real outputs; discovery is not acceptance.
05 resolves actual immutable packaging receipts and tests every selected image.
The final guest repeats this for host and each running container's real environment.
"""
import argparse, concurrent.futures, hashlib, importlib.util, json, os, re, subprocess, sys, time
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
            if target.get('baseComponent'):
                source,dependency=oci.local_base(root,target,pins)
                assert row['base']==source['ref']+'@'+source['digest'] and row['baseDependency']==dependency
            else:assert row['base']==target['base']
            assert row['key']==target['key']
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
 # Up to 3 attempts only for transport failures (35/52/56/28); acceptance (rc 0) fails at once.
 for try in 1 2 3; do rc=0; curl -fsS --max-time 20 https://$h.we-have-a-problem.com/ >/dev/null || rc=$?; case $rc in 35|52|56|28) sleep 2;; *) break;; esac; done
 test "$rc" = 60 || exit 41
done
if command -v node >/dev/null; then
 node -e 'const v=process.versions.node.split(".").map(Number),m={22:[22,23,4],24:[24,22,1],26:[26,12,1]},x=m[v[0]];if(!x||v[1]<x[1]||(v[1]===x[1]&&v[2]<x[2]))process.exit(42)'
 for h in example.com probe-emudhra.we-have-a-problem.com; do
 node -e 'const h=require("https");let r=h.get("https://"+process.argv[1]+"/",r=>{r.resume();if(r.statusCode!==200)process.exit(43)});r.setTimeout(20000,()=>process.exit(46));r.on("error",()=>process.exit(44))' $h
 done
 for h in HOSTS; do
 for try in 1 2 3; do rc=0; node -e 'const h=require("https");let r=h.get(process.argv[1],()=>process.exit(45));r.setTimeout(20000,()=>process.exit(46));r.on("error",e=>{if(!/^(CERT_|UNABLE_TO_|SELF_SIGNED_|DEPTH_ZERO_SELF_SIGNED_CERT|ERR_TLS_CERT_ALTNAME_INVALID)/.test(e.code||""))process.exit(47)})' https://$h.we-have-a-problem.com/ || rc=$?; case $rc in 46|47) sleep 2;; *) break;; esac; done
 test "$rc" = 0 || exit $rc
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


def inspect_container(docker, identity):
    return json.loads(run([docker, 'inspect', identity], timeout=20))[0]


def wait_stable(docker, identity, timeout=180, stable_seconds=10):
    """Do not mistake a single 'running' sample during a restart loop for readiness."""
    deadline=time.monotonic()+timeout; since=None; previous=None
    while time.monotonic()<deadline:
        row=inspect_container(docker,identity);state=row['State']
        token=(state.get('StartedAt'),row.get('RestartCount'))
        ready=(state.get('Running') and not any(state.get(k) for k in ['Restarting','Paused','Dead'])
               and state.get('Health',{}).get('Status','healthy')=='healthy')
        if ready:
            if token!=previous or since is None:since=time.monotonic()
            if time.monotonic()-since>=stable_seconds:return row
        else:since=None
        previous=token;time.sleep(min(2,max(0,deadline-time.monotonic())))
    raise TimeoutError('container not running/healthy with unchanged start/restart count within readiness deadline')


def internal_only(docker, row):
    networks=row['NetworkSettings']['Networks']
    if not networks:return False
    rows=json.loads(run([docker,'network','inspect',*networks],timeout=20))
    return len(rows)==len(networks) and all(n.get('Internal') is True for n in rows)


def internal_image_proof(root, image):
    plan=json.loads((root/'preparation/security-image-plan.json').read_text())
    receipt=json.loads((root/'security-preflight.json').read_text())
    assert receipt['passed'] is True and receipt['allGuestImagesEnumerated'] is True
    assert receipt['planSha256']==sha(root/'preparation/security-image-plan.json')
    assert receipt['resolutions']==plan['resolutions']
    # Only these two network-isolated infrastructure targets have this proof path.
    matches=[(key,r) for key,r in plan['resolutions'].items() if r['imageId']==image and key in {'postgres','rabbitmq'}]
    assert len(matches)==1,'no exact online-tested infrastructure image'
    key,resolution=matches[0]
    assert sha(root/resolution['receipt'])==resolution['receiptSha256']
    source=json.loads((root/resolution['receipt']).read_text())
    assert source['imageId']==image and source['ref']+'@'+source['digest']==resolution['image']
    checks=[c for c in receipt['checks'] if c['target']==resolution['image']]
    assert len(checks)==1 and checks[0]['returncode']==0,'missing full positive/negative image TLS proof'
    return {'target':key,'image':resolution['image'],'preflightSha256':sha(root/'security-preflight.json')}


def compare_internal(reference, actual):
    assert reference==actual,'running infrastructure trust inputs differ from the exact online-tested image'
    assert actual['contexts'] and actual['trustFiles'] and actual['runtimes']
    assert len(actual['rejectedAdvisoryRoots'])==4


def check_internal(docker,root,row,env):
    proof=internal_image_proof(root,row['Image'])
    source=(HERE/'security-internal.py').read_text()
    evidence=(HERE/'security-primary-evidence.json').read_text()
    # Code via -c, evidence via stdin; neither is written into the application.
    argv=['/bin/sh','-c', 'exec python3 -c "$1"', 'security-internal',source]
    reference=subprocess.run([docker,'run','--pull=never','--rm','-i','--network=none','--read-only',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=64m','--cap-drop=ALL','--security-opt=no-new-privileges',
        '--entrypoint',argv[0],row['Image'],*argv[1:]],input=evidence,text=True,capture_output=True,timeout=120,env=env)
    actual=subprocess.run([docker,'exec','-i',row['Id'],*argv],input=evidence,text=True,capture_output=True,timeout=120,env=env)
    assert reference.returncode==0,reference.stdout+reference.stderr
    assert actual.returncode==0,actual.stdout+actual.stderr
    expected=json.loads(reference.stdout);observed=json.loads(actual.stdout)
    compare_internal(expected,observed)
    proof.update(mode='internal-network-exact-trust-equivalence',snapshotSha256=hashlib.sha256(json.dumps(observed,sort_keys=True).encode()).hexdigest(),
                 rejectedAdvisoryRoots=observed['rejectedAdvisoryRoots'],contexts=list(observed['contexts']))
    return proof


def capture_failure(docker,identity,root):
    directory=root/'assembly-work/security-diagnostics';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    artifacts={}
    for key,argv in [('state',[docker,'inspect','--format','{{json .State}}',identity]),('logs',[docker,'logs','--tail','200',identity])]:
        path=directory/(identity+'.'+key+('.json' if key=='state' else '.log'))
        try:
            proc=subprocess.run(argv,text=True,capture_output=True,timeout=30)
            text=proc.stdout+proc.stderr
        except Exception as exc:text='diagnostic capture failed: '+str(exc)
        path.write_text(text);path.chmod(0o600);artifacts[key]=str(path.relative_to(root))
    return artifacts


def check_guest(docker,root,identity,image,env):
    result={'target':image,'container':identity,'returncode':1,'log':''}
    try:
        before=wait_stable(docker,identity)
        assert before['Image']==image,'container image changed'
        if internal_only(docker,before):
            result['proof']=check_internal(docker,root,before,env);result['returncode']=0
        else:
            proc=subprocess.run([docker,'exec','-i','-e','PYTHONDONTWRITEBYTECODE=1',identity,'/bin/sh','-s'],
                                input=PROBE,text=True,capture_output=True,timeout=1200,env=env)
            result.update(returncode=proc.returncode,log=proc.stdout+proc.stderr,mode='live-runtime-tls')
            if proc.returncode in {5,6,7,28,35,52,56}:result['log']='inconclusive network/transport failure; not certificate rejection\n'+result['log']
        after=inspect_container(docker,identity)
        assert after['State']['Running'] and not after['State'].get('Restarting')
        assert after['State'].get('Health',{}).get('Status','healthy')=='healthy'
        assert (after['State']['StartedAt'],after['RestartCount'])==(before['State']['StartedAt'],before['RestartCount']),'container restarted during security probe'
    except (TimeoutError,subprocess.TimeoutExpired) as exc:result.update(returncode=124,log='inconclusive: '+str(exc))
    except Exception as exc:result.update(returncode=1,log=str(exc))
    if result['returncode']!=0:result['diagnostics']=capture_failure(docker,identity,root)
    return result


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
    output=a.output or root/('assembly-work/security-guest.json' if a.guest else 'security-preflight.json')
    result={'schema':2,'passed':False,'images':images,'checks':[],'allGuestImagesEnumerated':False,'publishing':False,'resolutions':resolutions}
    if a.guest:
        host=subprocess.run(['sh','-s'],input=PROBE,text=True,capture_output=True,timeout=1200)
        result['checks'].append({'target':'guest-host','returncode':host.returncode,'log':host.stdout+host.stderr})
    def check(row):
        identity,image=row
        if a.guest:return check_guest(docker,root,identity,image,env)
        argv=[docker,'run','--pull=never','--rm','-i','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--entrypoint','/bin/sh',image,'-s']
        try:
            proc=subprocess.run(argv,input=PROBE,text=True,capture_output=True,timeout=1200,env=env)
            return {'target':image,'container':identity if a.guest else None,'returncode':proc.returncode,'log':proc.stdout+proc.stderr}
        except subprocess.TimeoutExpired:return {'target':image,'container':identity if a.guest else None,'returncode':124,'log':'inconclusive: timeout, never counted as certificate rejection'}
    # Serial images: >4 concurrent TLS handshakes through Colima corrupt records (curl 35 / bad record mac) and make rejection inconclusive.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:result['checks']+=list(pool.map(check,running))
    if a.guest:
        final_ids=set(run([docker,'ps','--no-trunc','-q']).split())
        initial_ids={identity for identity,_ in running}
        if final_ids!=initial_ids:
            result['checks'].append({'target':'guest-container-census','returncode':1,
                'log':'running/restarting container set changed during security checks',
                'before':sorted(initial_ids),'after':sorted(final_ids),
                'diagnostics':{identity:capture_failure(docker,identity,root) for identity in sorted(final_ids-initial_ids)}})
    result['passed']=bool(result['checks']) and all(x['returncode']==0 for x in result['checks'])
    result['allGuestImagesEnumerated']=result['passed'] and (a.guest or len(images)==len(plan['targets']))
    if not a.guest and result['passed']:
        plan.update(complete=True,status='all-selected-images-probed',images=images,resolutions=resolutions)
        (HERE/'security-image-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
        result['planSha256']=sha(HERE/'security-image-plan.json')
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'receipt':str(output),'imageCount':len(images)}));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
