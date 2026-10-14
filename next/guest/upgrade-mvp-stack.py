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
subprocess.run(['sudo','-iu','wizard','wam','apps','--json'],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['sudo','-u','wizard','env','XDG_RUNTIME_DIR=/run/user/1000','systemctl','--user','restart','wizard-app-manager-api','wizard-app-lifecycle','wizard-app-lifecycle-containers'],check=True)
subprocess.run(['systemctl','restart','wizard-local-proxy'],check=True)
cid=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.service=hermes-agent-engine'],text=True).strip()
if not cid or '\n' in cid: raise SystemExit('Ambiguous Hermes engine; refusing restart')
subprocess.run(['docker','restart','-t','20',cid],check=True,stdout=subprocess.DEVNULL)
after={str(p):digest(p) for p in protected}
if before!=after: raise SystemExit('Protected file changed unexpectedly; retained backup, do not claim migration passed')
(b/'applied.json').write_text(json.dumps({'patch':'mac-stack-v1','at':int(time.time()),'protected_unchanged':True})+'\n')
print('Mac stack patch applied; SOUL/account files unchanged. Disk, app data and chat databases were not replaced.')
