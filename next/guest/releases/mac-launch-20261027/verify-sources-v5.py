#!/usr/bin/env python3
"""v5 full source verification on Thales, Linux semantics and short AF_UNIX scratch.
No guest VM, native app build, release or image publication. Parent-submitted only.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path
import local_oci as oci
DOCKER='/opt/homebrew/bin/docker'
HERE=Path(__file__).resolve().parent
# WAM CI uses setup-python 3.11 (current patch), not Debian's unpatched 3.11.2.
# Supplement the existing Node 22/bookworm pin without changing frozen source pins.
PYTHON_IMAGE='python@sha256:18d373e126e39c29c6d38e71e2f19ca66636568318fc95c7849c462b7f9d3d64'

def linux_script():
    return '''set -eu
umask 022
cp -a /opt/ci-python/. /usr/local/; ldconfig
mkdir -p /work/t /work/src /work/logs; chmod 1777 /work/t
export TMPDIR=/work/t
# Hosted Ubuntu runners have these tools, system PyYAML and the Docker group.
# No daemon/socket is exposed to the test container.
apt-get update -qq && apt-get install -y -qq sudo python3-yaml restic
python3 -m venv /work/venv
/work/venv/bin/pip install pytest==9.1.1 pyyaml==6.0.3 pyjwt==2.15.1 python-dotenv==1.2.4 ruamel.yaml==0.19.1 cryptography==50.0.2 pycryptodome==4.2.0
/work/venv/bin/pip freeze > /work/logs/python-packages.txt
node --version > /work/logs/node-version.txt
python3 --version > /work/logs/python-version.txt
groupadd -f docker
usermod -aG docker node
printf 'node ALL=(ALL) NOPASSWD:ALL\\n' > /etc/sudoers.d/ci-node
chmod 440 /etc/sudoers.d/ci-node
for n in service ux wam; do cp -a /src/final/$n /work/src/$n; done
chown -R node:node /work/src /work/logs
# Tests replace HOME; system scope keeps this identity available in their git fixtures.
git config --system user.name 'Frozen source CI'
git config --system user.email 'source-ci@example.invalid'
sudo -H -u node env TMPDIR=/work/t bash -c '
set -eu
umask 022
for n in service ux wam; do
  cd /work/src/$n
  git init -q -b main
  git add -A
  git commit -qm "Frozen source export"
done
cd /work/src/service
# This immutable object is explicitly fetched by quality.yml for rollback tests.
git fetch --no-tags --depth=1 https://github.com/humanitylabs-org/wizard-agent-service.git 859c548d43081a5e28a37680e796d07041971601
npm ci --no-audit --no-fund
'
# Root-only managed recovery remains root; all ordinary CI suites run unprivileged.
rc=0
cd /work/src/service
python3 tests/managed_recovery_test.py > /work/logs/service-managed-root.log 2>&1 || rc=1
sudo -H -u node env TMPDIR=/work/t WIZARD_IMPORT_PYTHON=/work/venv/bin/python REQUIRE_ROLLBACK_REHEARSAL=1 bash <<'CI_SUITES' || rc=1
set -eu
rc=0
cd /work/src/service
node scripts/test-hermes-import.mjs > /work/logs/service-import.log 2>&1 || rc=1
npx vitest run --maxWorkers=4 > /work/logs/service-vitest.log 2>&1 || rc=1
node --test tests/session-text-search-worker.node.mjs tests/agent-archive-list.node.mjs tests/chat-photo-*.node.mjs tests/chats-install-e2e.node.mjs > /work/logs/service-unit-node.log 2>&1 || rc=1
python3 tests/test_chat_photo_reader.py > /work/logs/service-photo-reader.log 2>&1 || rc=1
python3 tests/test_standard_chats_relay.py > /work/logs/service-chats-relay.log 2>&1 || rc=1
node --test qa/agent-parity/fixture.test.mjs > /work/logs/service-agent-parity.log 2>&1 || rc=1
node --test tests/maintenance.node-test.mjs tests/app-lifecycle.node-test.mjs tests/app-view-adapters.node-test.mjs > /work/logs/service-maintenance.log 2>&1 || rc=1
cd /work/src/ux
node --test tests/*.test.mjs > /work/logs/ux-unit.log 2>&1 || rc=1
cd /work/src/wam
/work/venv/bin/python tests/test_portable_paths.py > /work/logs/wam-portable.log 2>&1 || rc=1
/work/venv/bin/python -m pytest -q -rs > /work/logs/wam-unit.log 2>&1 || rc=1
node --test tests/runtipi-open.test.mjs > /work/logs/wam-node.log 2>&1 || rc=1
exit $rc
CI_SUITES
exit $rc
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',required=True,type=Path);a=p.parse_args();root=a.stage_root.resolve()
    if sys.platform!='darwin' or not root.is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media'))):p.error('ThalesMedia only')
    pins=json.loads((HERE/'pins.json').read_text());checks=root/'source-checks-v5';checks.mkdir(exist_ok=False)
    result={'version':5,'finalPins':pins['finalPins'],'guestBuildStarted':False,'publishing':False,'commands':[]}
    env=oci.environment(checks)
    def run(key,argv,cwd=root,timeout=600):
        started=time.monotonic()
        with (checks/(key+'.log')).open('w') as log:
            proc=subprocess.run(list(map(str,argv)),cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        result['commands'].append({'key':key,'returncode':proc.returncode,'seconds':round(time.monotonic()-started,3)})
        (checks/'result.json').write_text(json.dumps(result,indent=2)+'\n');return proc.returncode==0
    # Linux full test suites require GNU bash, /proc, uid1000 and traversable temp parents.
    # macOS reruns do not substitute for these; no assertions/skips have been changed.
    mirrors={};image=oci.mirror(pins['sourceVerification']['linuxImage'],env,mirrors)
    python_image=oci.mirror(PYTHON_IMAGE,env,mirrors)
    (checks/'base-mirrors.json').write_text(json.dumps(mirrors,indent=2)+'\n')
    assert '@sha256:' in image and '@sha256:' in python_image
    result['ciEnvironment']={'nodeImage':image,'pythonImage':python_image,
        'testUser':'node (uid 1000)', 'managedRecoveryUser':'root',
        'gitCheckout':'owned committed exports + immutable service rollback object',
        'optionalCoverage':['ruamel.yaml','cryptography','pycryptodome']}
    container='mac-source-v5-'+hashlib.sha256(str(root).encode()).hexdigest()[:12]
    script=linux_script()
    (checks/'linux-script.sh').write_text(script)
    tools_volume=container+'-python';tools_created=False
    volume=container+'-source';copy_container=container+'-copy';mount=str(root)+':/src:ro';used_volume=False
    try:
        # Prove Colima sees the exact sentinel, not just an empty auto-created host directory.
        expected=oci.sha(root/'preparation/pins.json')
        visible=subprocess.run([DOCKER,'run','--rm','-v',mount,'--entrypoint','/bin/sh',image,'-c','sha256sum /src/preparation/pins.json'],env=env,capture_output=True,text=True,timeout=180)
        if visible.returncode or not visible.stdout.split() or visible.stdout.split()[0]!=expected:
            # External media is not necessarily shared by Colima. Copy only the source inputs
            # into a unique daemon-owned volume; no image archives or host secrets.
            subprocess.run([DOCKER,'volume','create',volume],env=env,check=True,capture_output=True);used_volume=True
            subprocess.run([DOCKER,'create','--name',copy_container,'-v',volume+':/src',image,'true'],env=env,check=True,capture_output=True)
            try:
                subprocess.run([DOCKER,'cp',str(root/'final'),copy_container+':/src/final'],env=env,check=True,timeout=180)
                copied=run('source-volume-readback',[DOCKER,'run','--rm','-v',volume+':/src:ro','--entrypoint','/bin/sh',image,'-c','sha256sum /src/final/service/.wizard-source.json'],timeout=60)
                assert copied and (checks/'source-volume-readback.log').read_text().split()[0]==oci.sha(root/'final/service/.wizard-source.json'),'named source copy not visible'
            finally:subprocess.run([DOCKER,'rm',copy_container],env=env,check=True,capture_output=True)
            mount=volume+':/src:ro'
        result['sourceMount']={'mode':'named-volume-copy' if used_volume else 'verified-host-bind','pinsSha256':expected,'dockerHost':oci.SOCKET}
        subprocess.run([DOCKER,'volume','create',tools_volume],env=env,check=True,capture_output=True);tools_created=True
        assert run('python-tools',[DOCKER,'run','--rm','--platform','linux/arm64','-v',tools_volume+':/python',python_image,'bash','-ec','python3 --version; cp -a /usr/local/. /python/'],timeout=300)
        if run('linux-create',[DOCKER,'create','--name',container,'--platform','linux/arm64','-v',mount,'-v',tools_volume+':/opt/ci-python:ro',image,'bash','-lc',script],timeout=90):
            try:
                run('linux-full',[DOCKER,'start','-a',container],timeout=1500)
            finally:
                run('linux-logs',[DOCKER,'cp',container+':/work/logs',checks/'linux-logs'],timeout=90)
    finally:
        subprocess.run([DOCKER,'rm','-fv',container],env=env,check=False,capture_output=True,timeout=60)
        if used_volume:subprocess.run([DOCKER,'volume','rm',volume],env=env,check=True,capture_output=True,timeout=60)
        if tools_created:subprocess.run([DOCKER,'volume','rm',tools_volume],env=env,check=True,capture_output=True,timeout=60)
    native=checks/'native';shutil.copytree(root/'final/native',native,symlinks=True)
    for key,args in [('overlay-tool-modes',['-m','unittest','discover','-s','next/guest/tests','-p','test_overlay_tool_modes.py']),('managed-interpreters',['-m','unittest','discover','-s','next/guest/tests','-p','test_managed_interpreters.py']),('factory-pins',['-m','unittest','discover','-s','next/guest/tests','-p','test_release_pins.py']),('phone',['-m','unittest','discover','-s','next/guest/tests','-p','test_phone_access.py']),('stock-builder',['-m','unittest','discover','-s','next/tests','-p','test_stock_builder.py']),('factory-admission',['next/mac/tools/check-factory-admission.py','--work',str(checks/'admission')])]:
        run(key,['/opt/homebrew/bin/python3',*args],native,180)
    result['passed']=bool(result['commands']) and all(x['returncode']==0 for x in result['commands'])
    (checks/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
