#!/usr/bin/env python3
"""Opt-in real import/undo on an owned disposable guest; no product mocks.
No provider/model change: the synthetic archive retains this QA home's config.
Run at least 65 seconds after other authenticated retirement fixtures.
"""
import argparse,fcntl,hashlib,importlib.util,json,sqlite3,subprocess as sp,sys,time,uuid,zipfile
from pathlib import Path
sys.path.insert(0,'/opt/wizard/agent-runtime');from managed_maintenance import ManagedMaintenance,MaintenanceError
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('preservation',Path(__file__).parents[1]/'stack-preservation.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
data=Path('/home/wizard/runtipi/app-data/wizardapps/hermes-agent/data');m=ManagedMaintenance();rows=[]
def save(name,**kw):
 rows.append({'gate':name,'passed':True,**kw});(out/'real-import.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,'PASS',flush=True)
def hashes():return {x:hashlib.sha256((data/x).read_bytes()).hexdigest() for x in ['SOUL.md','.env']}
def auth():return g.auth_snapshot(json.loads((data/'auth.json').read_text()))
def sessions():
 with sqlite3.connect('file:'+str(data/'state.db')+'?mode=ro',uri=True) as db:
  return {t:hashlib.sha256(repr(list(db.execute('SELECT * FROM '+t+' ORDER BY id'))).encode()).hexdigest() for t in ['sessions','messages']}
def busy():
 for path in (m.root/'operations').iterdir():
  try:
   with path.open() as f:
    try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return True
  except FileNotFoundError:pass
 return False
before=hashes();auth_before=auth();sessions_before=sessions()
z=Path('/var/lib/wizard')/('synthetic-import-'+uuid.uuid4().hex+'.zip')
with zipfile.ZipFile(z,'w') as f:
 f.writestr('SOUL.md','# Synthetic Recovery QA\n\nDisposable import proof.\n');f.write(data/'config.yaml','config.yaml')
z.chmod(0o600)
script='/opt/wizard/bin/wizard-import-hermes';token=str(uuid.uuid4());m.acquire(token)
try:
 result=sp.run([script,'file',str(z)],capture_output=True,text=True,timeout=30);payload=json.loads(result.stdout)
 assert result.returncode!=0 and payload.get('detail')=='maintenance_active',payload.get('error')
 assert hashes()==before;save('real_import_refused_during_update_before_mutation')
finally:m.release(token)
proc=sp.Popen([script,'file',str(z)],stdout=sp.PIPE,stderr=sp.PIPE,text=True)
try:
 for _ in range(500):
  if busy():break
  assert proc.poll() is None,'import exited before reservation observation';time.sleep(.01)
 else:raise AssertionError('no owned reservation')
 try:m.acquire(str(uuid.uuid4()));raise AssertionError('admitted during import')
 except MaintenanceError as e:assert str(e)=='runtime_operation_in_flight',str(e)
 save('real_owned_import_reservation_refuses_update')
 stdout,stderr=proc.communicate(timeout=300);payload=json.loads(stdout)
 assert proc.returncode==0 and payload['ok'],{'exit':proc.returncode,'error':payload.get('error'),'detail':payload.get('detail')}
 assert (data/'SOUL.md').read_text().startswith('# Synthetic Recovery QA')
 save('real_guarded_synthetic_import',stockCLI=True,userUID=1000,managedStateMounted=True)
finally:
 if proc.poll() is None:proc.wait(timeout=300)
result=sp.run([script,'undo'],capture_output=True,text=True,timeout=300);payload=json.loads(result.stdout)
assert result.returncode==0 and payload['ok'],{'exit':result.returncode,'error':payload.get('error'),'detail':payload.get('detail')}
assert hashes()==before;auth_proof=g.compare_auth(auth_before,auth());assert auth_proof['stable_identity_credentials_preserved'],auth_proof['unexpected_field_changes']
assert sessions()==sessions_before
assert not busy();assert m.read() is None and not (m.root/'resume.json').exists();z.unlink()
save('real_guarded_undo_restores_identity_credentials_and_rows',soulEnvByteEqual=True,permanentAuth=auth_proof,sessionAndMessageRowsEqual=True)
