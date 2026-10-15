#!/usr/bin/env python3
"""Apply this bounded Mac MVP runtime patch inside an existing guest. No factory trim/reset.
Payload: wam/wam/, overlay/opt/wizard/, wizard-shell.tar; invoke --apply only after host disk backup.
"""
import argparse, hashlib, importlib.util, json, os, shutil, subprocess, sys, time, yaml
from pathlib import Path
spec=importlib.util.spec_from_file_location('stack_preservation',Path(__file__).with_name('stack-preservation.py'))
if spec is None or spec.loader is None: raise SystemExit('Missing preservation helper')
guard=importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
p=argparse.ArgumentParser(); p.add_argument('payload',type=Path); p.add_argument('--apply',action='store_true'); a=p.parse_args()
if os.geteuid()!=0: raise SystemExit('Run as root inside the Wizard guest')
root=Path('/home/wizard/runtipi'); data=root/'app-data/wizardapps/hermes-agent/data'
if not (data/'config.yaml').is_file(): raise SystemExit('Existing MVP Hermes config not found; refusing unknown layout')
for required in ('wam/wam/registry.py','wam/wam/fresh_agent.py','overlay/opt/wizard/local-proxy.conf','overlay/opt/wizard/bin/wizard-product-configure','overlay/opt/wizard/bin/wizard-runtime-configure','agent-runtime/agent_runtime.py','runtime-bom.json','wizard-shell.tar'):
 if not (a.payload/required).is_file(): raise SystemExit('Incomplete payload: '+required)
bom=json.loads((a.payload/'runtime-bom.json').read_text())
with (a.payload/'wizard-shell.tar').open('rb') as f: payload_sha256=hashlib.file_digest(f,'sha256').hexdigest()
if payload_sha256!=bom['payload_sha256']: raise SystemExit('Payload digest mismatch')
managed=bom.get('managed_runtime')
if managed:
 with (a.payload/'wizard-hermes-managed.tar').open('rb') as f:
  if hashlib.file_digest(f,'sha256').hexdigest()!=managed['sha256']:raise SystemExit('Managed image digest mismatch')
 if managed.get('stock')!='f97608f178d1ffeca59860195ab7da295f7c8e5f':raise SystemExit('Unknown stock maintenance contract')
for relative,expected in bom.get('files',{}).items():
 p=a.payload/relative
 if Path(relative).is_absolute() or '..' in Path(relative).parts or p.is_symlink(): raise SystemExit('Unsafe BOM member')
 with p.open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
 if actual!=expected: raise SystemExit('BOM file mismatch: '+relative)
if not a.apply: print('Preflight passed. Quit chat activity and back up the stopped VM disk before --apply.'); raise SystemExit(0)
# Owned metadata backup only; it contains private account config, stays in guest mode0700, never logs bytes.
b=Path('/var/lib/wizard/patches/mac-stack-v1'); b.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(b,0o700)
# A failed new attempt must never leave a stale success receipt.
if (b/'applied.json').exists(): (b/'applied.json').replace(b/('applied-history-'+str(time.time_ns())+'.json'))
for src in (data/'config.yaml',root/'user-config/wizardapps/wizard-shell/docker-compose.yml',Path('/opt/wizard/local-proxy.conf'),Path('/home/wizard/.wizard-os/app-manager.json')):
 dst=b/(str(src).replace('/','_'))
 if src.is_file() and not dst.exists(): shutil.copy2(src,dst); os.chmod(dst,0o600)
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
protected=[data/'SOUL.md',data/'.env',data/'auth.json']
before={str(p):digest(p) for p in protected}
before_env=(data/'.env').read_bytes()
managed_key=Path('/home/wizard/.wizard-os/agent-ssh/id_ed25519')
managed_key_before=digest(managed_key)
legacy_key_before=digest(data/'.ssh-vm/id_ed25519')
before_model=yaml.safe_load((data/'config.yaml').read_text()).get('model')
runtime_tokens=root/'app-data/wizard-os/runtime-secrets'
tokens_before={p.name:digest(p) for p in runtime_tokens.glob('*') if p.is_file()}
def auth_snapshot():
    path=data/'auth.json'
    raw=path.read_bytes() if path.is_file() else None
    return (hashlib.sha256(raw).hexdigest() if raw is not None else None,
            guard.auth_snapshot(json.loads(raw) if raw is not None else None))
before_auth_hash,before_auth=auth_snapshot()
before[str(data/'auth.json')]=before_auth_hash
before_engine_cid=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.service=hermes-agent-engine'],text=True).strip()
if not before_engine_cid or '\n' in before_engine_cid: raise SystemExit('Ambiguous Hermes engine before migration')
before_engine_image=subprocess.check_output(['docker','inspect',before_engine_cid,'--format','{{.Image}}'],text=True).strip()
# No .git or existing home replacement: install only the WAM package and this guest overlay's named files.
shutil.copytree(a.payload/'wam/wam',Path('/home/wizard/wizard-app-manager/wam'),dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
for rel in ('product-plugin','bin/wizard-product-configure','setup/hermes_brain.py','local-proxy.conf',
            # Bring My Hermes into Wizard (front door /api/agent-import) and the agent-key move out of app-data.
            'bin/wizard-import-hermes','bin/wizard-agent-ssh-migrate','bin/wizard-apps','bin/wizard-runtime-configure','setup/server.py',
            'setup/static/index.html','setup/static/wizard-icon-32.png','setup/static/wizard-mark-white.png',
            'bin/wizard-setup-start','voice/engine.py','voice/start.sh','bin/wizard-media','bin/wizard-ux-bridge','bin/wizard-env','bin/wizard-firstboot'):
 src=a.payload/'overlay/opt/wizard'/rel; dst=Path('/opt/wizard')/rel
 if not src.exists() and rel.startswith(('bin/wizard-import','bin/wizard-agent-ssh','bin/wizard-apps','setup/server')): continue
 if src.is_dir(): shutil.copytree(src,dst,dirs_exist_ok=True)
 else: shutil.copy2(src,dst)
shutil.copytree(a.payload/'agent-runtime',Path('/opt/wizard/agent-runtime'),dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
for tool in ('wizard-product-configure','wizard-import-hermes','wizard-agent-ssh-migrate','wizard-apps','wizard-runtime-configure','wizard-media','wizard-ux-bridge','wizard-env','wizard-firstboot'):
 if Path('/opt/wizard/bin',tool).is_file(): os.chmod(Path('/opt/wizard/bin',tool),0o755)
subprocess.run(['/opt/wizard/bin/wizard-product-configure'],check=True)
subprocess.run(['docker','load','-i',str(a.payload/'wizard-shell.tar')],check=True,stdout=subprocess.DEVNULL)
if managed:
 subprocess.run(['docker','load','-i',str(a.payload/'wizard-hermes-managed.tar')],check=True,stdout=subprocess.DEVNULL)
 base=json.loads(subprocess.check_output(['docker','image','inspect',bom['stock_hermes']['image_id']],text=True))[0]
 image=json.loads(subprocess.check_output(['docker','image','inspect',managed['image']],text=True))[0]
 if image['RootFS']['Layers'][:len(base['RootFS']['Layers'])]!=base['RootFS']['Layers'] or image['Config']['Labels'].get('ai.wizards.managed-launch')!='1':raise SystemExit('Managed runtime is not the pinned stock packaging layer')
 shutil.copy2(a.payload/'managed-runtime.json','/opt/wizard/managed-runtime.json');os.chmod('/opt/wizard/managed-runtime.json',0o644)
 sys.path.insert(0,'/opt/wizard/agent-runtime')
 from managed_maintenance import ManagedMaintenance
 ManagedMaintenance()
# This source pin intentionally retains the shipped local image tag; docker load replaces only that local tag.
# Runtipi's supported lifecycle recreates containers, preserving all mounted app data.
held=Path('/var/lib/wizard/managed/lease.json').is_file()
if held:
 refresh="import sys;sys.path.insert(0,'/home/wizard/wizard-app-manager');from wam import cli,fresh_agent;fresh_agent.maintenance_refresh(cli.Config())"
 subprocess.run(['sudo','-u','wizard','env','HOME=/home/wizard','python3','-c',refresh],check=True,stdout=subprocess.DEVNULL)
else:subprocess.run(['sudo','-iu','wizard','wam','fresh-agent','connect'],check=True,stdout=subprocess.DEVNULL)
# The agent's terminal key now mounts from ~/.wizard-os/agent-ssh (read-only), out of reach of Runtipi's start-time chmod.
ssh_report={}
if held:
 # The maintenance boot must not launch ordinary Hermes config/inspection CLIs.
 # This owned new-VM contract already migrated the key; preserve it, fail closed
 # on an older layout instead of silently bypassing executable admission.
 if yaml.safe_load((data/'config.yaml').read_text()).get('terminal',{}).get('ssh_key')!='/opt/agent-ssh/id_ed25519' or not managed_key.is_file():raise SystemExit('SSH key requires pre-maintenance migration')
elif Path('/opt/wizard/bin/wizard-agent-ssh-migrate').is_file():
 ssh_report=json.loads(subprocess.check_output(['/opt/wizard/bin/wizard-agent-ssh-migrate'],text=True))
subprocess.run(['/opt/wizard/bin/wizard-runtime-configure'],check=True)
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
after_engine_image=subprocess.check_output(['docker','inspect',cid,'--format','{{.Image}}'],text=True).strip()
if after_engine_image!=(managed['image'] if managed else before_engine_image): raise SystemExit('Engine image differs from authenticated packaging BOM; no success receipt')
subprocess.run(['docker','restart','-t','20',cid],check=True,stdout=subprocess.DEVNULL)
expected_image=subprocess.check_output(['docker','image','inspect','wizard-shell:mac-mvp-20261013','--format','{{.Id}}'],text=True).strip()
service_cid=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.service=wizard-shell'],text=True).strip()
if not service_cid or '\n' in service_cid: raise SystemExit('Ambiguous MVP Service container')
actual_image=subprocess.check_output(['docker','inspect',service_cid,'--format','{{.Image}}'],text=True).strip()
if actual_image!=bom['service_image_id']: raise SystemExit('Running Service differs from immutable BOM')
if actual_image!=expected_image: raise SystemExit('Service did not load the new image; no success receipt written')
subprocess.run(['systemctl','is-active','--quiet','wizard-agent-runtime','wizard-runtime-proxy'],check=True)
if yaml.safe_load((data/'config.yaml').read_text()).get('model')!=before_model: raise SystemExit('Configured model changed')
if any(digest(runtime_tokens/n)!=v for n,v in tokens_before.items()): raise SystemExit('Existing runtime token changed')
after={str(p):digest(p) for p in protected}
after_auth_hash,after_auth=auth_snapshot()
after[str(data/'auth.json')]=after_auth_hash
auth_report=guard.compare_auth(before_auth,after_auth)
changed=[Path(p).name for p in before if before[p]!=after[p]]
env_report=guard.compare_env(before_env,(data/'.env').read_bytes(),managed_ssh_verified=bool(ssh_report.get('ssh_probe') and managed_key_before and managed_key_before==legacy_key_before==digest(managed_key)))
other_changed=[p for p in changed if p not in ('auth.json','.env')]
report={'env':env_report,'source_pins':bom['sources'],'runtime_bom_sha256':digest(a.payload/'runtime-bom.json'),'configured_model_preserved':True,'runtime_tokens_preserved':True,'patch':'mac-stack-v1','at':int(time.time()),'protected_files_byte_unchanged':before==after,'protected_before_sha256':before,'protected_after_sha256':after,'permanent_identity_credentials_preserved':auth_report['stable_identity_credentials_preserved'],'auth':auth_report,'service_image':actual_image,'engine_image_unchanged':before_engine_image==after_engine_image,'engine_image':after_engine_image}
if managed:
 report['managed_runtime_image']=managed['image'];report['stock_base_image_preserved']=bom['stock_hermes']['image_id'];report['maintenance_admission_held']=held
(b/'preservation-latest.json').write_text(json.dumps(report,sort_keys=True)+'\n')
if other_changed or not env_report['stable_credentials_preserved'] or not auth_report['stable_identity_credentials_preserved']:
    (b/'preservation-failure.json').write_text(json.dumps(report,sort_keys=True)+'\n')
    raise SystemExit('Protected state mutation: '+repr(other_changed)+'; unexpected auth paths='+repr([c['path'] for c in auth_report['unexpected_field_changes']])+'; retained backup, no success receipt')
(b/'applied.json').write_text(json.dumps(report,sort_keys=True)+'\n')
print('Mac stack patch applied; SOUL/env and permanent account credentials preserved; stock invoke-grant rotation/runtime metadata audited by field hashes. Disk, app data and chat databases were not replaced.')
