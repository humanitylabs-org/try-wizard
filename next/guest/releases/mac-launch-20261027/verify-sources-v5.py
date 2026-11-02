#!/usr/bin/env python3
"""v5 full source verification on Thales, Linux semantics and short AF_UNIX scratch.
No guest VM, native app build, release or image publication. Parent-submitted only.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path
DOCKER='/opt/homebrew/bin/docker'
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',required=True,type=Path);a=p.parse_args();root=a.stage_root.resolve()
    if sys.platform!='darwin' or not root.is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media'))):p.error('ThalesMedia only')
    pins=json.loads((HERE/'pins.json').read_text());checks=root/'source-checks-v5';checks.mkdir(exist_ok=False)
    result={'version':5,'finalPins':pins['finalPins'],'guestBuildStarted':False,'publishing':False,'commands':[]}
    env={**os.environ,'PATH':'/opt/homebrew/bin:'+os.environ.get('PATH',''),'TMPDIR':str(checks)}
    def run(key,argv,cwd=root,timeout=600):
        started=time.monotonic()
        with (checks/(key+'.log')).open('w') as log:
            proc=subprocess.run(list(map(str,argv)),cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        result['commands'].append({'key':key,'returncode':proc.returncode,'seconds':round(time.monotonic()-started,3)})
        (checks/'result.json').write_text(json.dumps(result,indent=2)+'\n');return proc.returncode==0
    # Linux full test suites require GNU bash, /proc, uid1000 and traversable temp parents.
    # macOS reruns do not substitute for these; no assertions/skips have been changed.
    image=pins['sourceVerification']['linuxImage']
    assert '@sha256:' in image
    container='mac-source-v5-'+hashlib.sha256(str(root).encode()).hexdigest()[:12]
    script='''set -eu
mkdir -p /work/t /work/src /work/logs; chmod 1777 /work/t
export TMPDIR=/work/t
apt-get update -qq && apt-get install -y -qq python3-venv python3-pip sudo
python3 -m venv /work/venv
/work/venv/bin/pip install pytest==9.1.1 pyyaml==6.0.3 pyjwt==2.15.1
for n in service ux wam; do cp -a /src/final/$n /work/src/$n; cd /work/src/$n; git init -q; git add -A; done
rc=0
cd /work/src/service
npm ci --ignore-scripts --no-audit --no-fund
npx vitest run --maxWorkers=4 > /work/logs/service-vitest.log 2>&1 || rc=1
node --test tests/maintenance.node-test.mjs tests/app-lifecycle.node-test.mjs tests/app-view-adapters.node-test.mjs > /work/logs/service-maintenance.log 2>&1 || rc=1
python3 tests/managed_recovery_test.py > /work/logs/service-managed-root.log 2>&1 || rc=1
cd /work/src/ux
node --test tests/*.test.mjs > /work/logs/ux-unit.log 2>&1 || rc=1
cd /work/src/wam
/work/venv/bin/python -m pytest -q -rs > /work/logs/wam-unit.log 2>&1 || rc=1
exit $rc
'''
    try:
        if run('linux-create',[DOCKER,'create','--name',container,'--platform','linux/arm64','-v',str(root)+':/src:ro',image,'bash','-lc',script],timeout=90):
            try:
                run('linux-full',[DOCKER,'start','-a',container],timeout=1500)
            finally:
                run('linux-logs',[DOCKER,'cp',container+':/work/logs',checks/'linux-logs'],timeout=90)
    finally:
        subprocess.run([DOCKER,'rm','-fv',container],env=env,check=False,capture_output=True,timeout=60)
    native=checks/'native';shutil.copytree(root/'final/native',native,symlinks=True)
    for key,args in [('factory-pins',['-m','unittest','discover','-s','next/guest/tests','-p','test_release_pins.py']),('phone',['-m','unittest','discover','-s','next/guest/tests','-p','test_phone_access.py']),('stock-builder',['-m','unittest','discover','-s','next/tests','-p','test_stock_builder.py']),('factory-admission',['next/mac/tools/check-factory-admission.py','--work',str(checks/'admission')])]:
        run(key,['/opt/homebrew/bin/python3',*args],native,180)
    result['passed']=bool(result['commands']) and all(x['returncode']==0 for x in result['commands'])
    (checks/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
