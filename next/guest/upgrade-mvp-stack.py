#!/usr/bin/env python3
"""Apply this bounded Mac MVP runtime patch inside an existing guest. No factory trim/reset.
Payload: wam/wam/, overlay/opt/wizard/, wizard-shell.tar; invoke --apply only after host disk backup.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('payload',type=Path); p.add_argument('--apply',action='store_true'); a=p.parse_args()
if os.geteuid()!=0: raise SystemExit('Run as root inside the Wizard guest')
root=Path('/home/wizard/runtipi'); data=root/'app-data/wizardapps/hermes-agent/data'
if not (data/'config.yaml').is_file(): raise SystemExit('Existing MVP Hermes config not found; refusing unknown layout')
for required in ('wam/wam/registry.py','wam/wam/fresh_agent.py','overlay/opt/wizard/local-proxy.conf','overlay/opt/wizard/bin/wizard-product-configure','wizard-shell.tar'):
 if not (a.payload/required).is_file(): raise SystemExit('Incomplete payload: '+required)
if not a.apply: print('Preflight passed. Quit chat activity and back up the stopped VM disk before --apply.'); raise SystemExit(0)
# Owned metadata backup only; it contains private account config, stays in guest mode0700, never logs bytes.
b=Path('/var/lib/wizard/patches/mac-stack-v1'); b.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(b,0o700)
for src in (data/'config.yaml',root/'user-config/wizardapps/wizard-shell/docker-compose.yml',Path('/opt/wizard/local-proxy.conf'),Path('/home/wizard/.wizard-os/app-manager.json')):
 dst=b/(str(src).replace('/','_'))
 if src.is_file() and not dst.exists(): shutil.copy2(src,dst); os.chmod(dst,0o600)
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
protected=[data/'SOUL.md',data/'.env',data/'auth.json']
before={str(p):digest(p) for p in protected}
def auth_leaves():
    path=data/'auth.json'
    if not path.is_file(): return {}
    doc=json.loads(path.read_text()); leaves={}
    def visit(value, path):
        if isinstance(value,dict):
            for k,v in value.items(): visit(v,path+'.'+str(k))
        elif isinstance(value,list):
            for i,v in enumerate(value): visit(v,path+'.'+str(i))
        else: leaves[path]=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    visit(doc,'auth'); return leaves
before_auth=auth_leaves()
# No .git or existing home replacement: install only the WAM package and this guest overlay's named files.
shutil.copytree(a.payload/'wam/wam',Path('/home/wizard/wizard-app-manager/wam'),dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
for rel in ('product-plugin','bin/wizard-product-configure','setup/hermes_brain.py','local-proxy.conf'):
 src=a.payload/'overlay/opt/wizard'/rel; dst=Path('/opt/wizard')/rel
 if src.is_dir(): shutil.copytree(src,dst,dirs_exist_ok=True)
 else: shutil.copy2(src,dst)
os.chmod('/opt/wizard/bin/wizard-product-configure',0o755)
subprocess.run(['/opt/wizard/bin/wizard-product-configure'],check=True)
subprocess.run(['docker','load','-i',str(a.payload/'wizard-shell.tar')],check=True,stdout=subprocess.DEVNULL)
# This source pin intentionally retains the shipped local image tag; docker load replaces only that local tag.
# Runtipi's supported lifecycle recreates containers, preserving all mounted app data.
subprocess.run(['sudo','-iu','wizard','wam','fresh-agent','connect'],check=True,stdout=subprocess.DEVNULL)
# A re-applied payload may change only the local image, not the generated overlay; force this one app to reload it.
restart_service = """import sys
sys.path.insert(0, '/home/wizard/wizard-app-manager')
from wam import cli
r=cli.Config().runtipi(); urn='wizard-shell:wizardapps'
r.req('POST', '/app-lifecycle/'+urn+'/stop', {}, timeout=300)
r.wait_status(urn, {'stopped'}, timeout=600)
r.req('POST', '/app-lifecycle/'+urn+'/start', {}, timeout=300)
r.wait_status(urn, {'running'}, timeout=600)
"""
subprocess.run(['sudo','-u','wizard','env','HOME=/home/wizard','python3','-c',restart_service],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['sudo','-iu','wizard','wam','apps','--json'],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['sudo','-u','wizard','env','XDG_RUNTIME_DIR=/run/user/1000','systemctl','--user','restart','wizard-app-manager-api','wizard-app-lifecycle','wizard-app-lifecycle-containers'],check=True)
subprocess.run(['systemctl','restart','wizard-local-proxy','wizard-setup'],check=True)
cid=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.service=hermes-agent-engine'],text=True).strip()
if not cid or '\n' in cid: raise SystemExit('Ambiguous Hermes engine; refusing restart')
subprocess.run(['docker','restart','-t','20',cid],check=True,stdout=subprocess.DEVNULL)
expected_image=subprocess.check_output(['docker','image','inspect','wizard-shell:mac-mvp-20261013','--format','{{.Id}}'],text=True).strip()
service_cid=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.service=wizard-shell'],text=True).strip()
if not service_cid or '\n' in service_cid: raise SystemExit('Ambiguous MVP Service container')
actual_image=subprocess.check_output(['docker','inspect',service_cid,'--format','{{.Image}}'],text=True).strip()
if actual_image!=expected_image: raise SystemExit('Service did not load the new image; no success receipt written')
after={str(p):digest(p) for p in protected}
if before!=after:
    changed=[Path(p).name for p in before if before[p]!=after[p]]
    after_auth=auth_leaves(); changed_paths=[k for k in set(before_auth)|set(after_auth) if before_auth.get(k)!=after_auth.get(k)]
    (b/'preservation-failure.json').write_text(json.dumps({'changed_files':changed,'auth_field_paths_changed':changed_paths,'before':before,'after':after})+'\n')
    raise SystemExit('Protected file changed unexpectedly: '+', '.join(changed)+'; auth field paths changed='+repr(changed_paths)+'; retained backup, do not claim migration passed')
(b/'applied.json').write_text(json.dumps({'patch':'mac-stack-v1','at':int(time.time()),'protected_unchanged':True,'service_image':actual_image})+'\n')
print('Mac stack patch applied; SOUL/account files unchanged. Disk, app data and chat databases were not replaced.')
