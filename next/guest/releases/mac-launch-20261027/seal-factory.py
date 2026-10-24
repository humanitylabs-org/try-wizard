#!/usr/bin/env python3
"""Seal ONLY a never-onboarded owned factory guest, then power off.
This refuses a used guest before changing anything. Archive/compression is external.
"""
import hashlib,json,os,shutil,sqlite3,subprocess,time
from pathlib import Path
R=Path('/mnt/launch/assembly-work');H=Path('/home/wizard/runtipi/app-data/wizardapps/hermes-agent/data');OS=Path('/home/wizard/runtipi/app-data/wizard-os');S=Path('/home/wizard/runtipi/app-data/wizardapps/wizard-shell/data')
assert os.geteuid()==0
for name in ['auth.json','anon_auth.json','guest_identity.json']:
 p=H/name;assert not p.exists() or not p.stat().st_size,'Factory has account identity: '+name
assert not Path('/var/lib/wizard/setup.json').exists(),'Factory has onboarding state'
for p in H.glob('*.db'):
 c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
 if c.execute("select name from sqlite_master where name='sessions'").fetchone():assert c.execute('select count(*) from sessions').fetchone()[0]==0,'Factory has sessions'
 c.close()
assert not list((OS/'agents').glob('*/agent.json')),'Factory has created agents'
units=['wizard-agent-runtime','wizard-runtime-proxy','wizard-runtime-secrets','wizard-setup','wizard-local-proxy','wizard-ux-bridge','wizard-voice']
subprocess.run(['systemctl','stop',*units],check=True)
subprocess.run(['sudo','-u','wizard','env','XDG_RUNTIME_DIR=/run/user/1000','systemctl','--user','stop','wizard-app-manager-api','wizard-app-lifecycle','wizard-app-lifecycle-containers'],check=True)
ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
if ids:subprocess.run(['docker','stop',*ids],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['systemctl','stop','docker.service','docker.socket','containerd.service'],check=True)
containers=[]
for p in Path('/var/lib/docker/containers').glob('*/config.v2.json'):
 d=json.loads(p.read_text());d['HasBeenManuallyStopped']=False;p.write_text(json.dumps(d));containers.append({'name':d['Name'],'image':d['Image']})
# Newly-added runtime stores/tokens must be recipient-owned, empty in the factory.
for p in [OS/'runtime-secrets',OS/'agents',S/'wizard-os/app-tokens',S/'wizard-os/agents',S/'upload-staging',Path('/home/wizard/.wizard-os/agent-ssh'),Path('/home/wizard/.ssh'),H/'.ssh-vm',H/'backups',Path('/var/lib/wizard/patches')]:
 if p.exists():shutil.rmtree(p)
for p in [S/'wizard-os/app-bindings.json',S/'wizard-os/agent-grants.json',S/'uploads.sqlite3',S/'uploads.sqlite3-wal',S/'uploads.sqlite3-shm',S/'user-files.json',Path('/var/lib/wizard/portrait'),Path('/var/lib/wizard/voice.json'),Path('/home/wizard/.wizard-os/private-access.json'),Path('/var/lib/dbus/machine-id'),Path('/home/wizard/.bash_history'),Path('/root/.bash_history')]:p.unlink(missing_ok=True)
for p in Path('/etc/ssh').glob('ssh_host_*'):p.unlink()
for p in Path('/var/lib/tailscale').glob('*.state'):p.unlink()
Path('/etc/machine-id').write_text('')
# No developer checkout history is included.
if Path('/home/wizard/wizard-app-manager/.git').exists():shutil.rmtree('/home/wizard/wizard-app-manager/.git')
pins=json.loads((R/'source-pins.json').read_text());Path('/home/wizard/wizard-app-manager/SOURCE_COMMIT').write_text(pins['wam']+'\n')
receipt={'schema':1,'pristine':True,'sources':pins,'containers':containers,'runtime_secrets_absent':not (OS/'runtime-secrets').exists(),'agent_stores_empty':not (OS/'agents').exists(),'account_identity_absent':True,'sessions_empty':True,'ssh_and_machine_identity_absent':True,'factory_runtime_secrets_unit_enabled':Path('/etc/systemd/system/multi-user.target.wants/wizard-runtime-secrets.service').is_symlink()}
(R/'factory-sanitization.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2),flush=True)
subprocess.run(['journalctl','--rotate'],check=True);subprocess.run(['journalctl','--vacuum-time=1s'],check=True)
os.sync();subprocess.run(['systemctl','poweroff'],check=True)
