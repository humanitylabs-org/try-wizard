#!/usr/bin/env python3
"""Opt-in disposable-guest proof. Uses installed production helpers and real
stock HTTP retirement; fault injection drops only the outer transport reply or
kills this helper AFTER the real commit. Never monkeypatches Hermes modules.
Run only on the owned QA clone; --output points at a private receipt directory.
"""
import argparse,hashlib,json,os,subprocess as sp,sys,time,uuid,zipfile
from pathlib import Path
sys.path.insert(0,'/opt/wizard/agent-runtime')
from managed_maintenance import ManagedMaintenance,MaintenanceError
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
rows=[]
def save(gate,**kw):
 rows.append({'gate':gate,'passed':True,**kw});(a.output/'real-recovery.json').write_text(json.dumps(rows,indent=2)+'\n');print(gate,'PASS',flush=True)
def ready(m):
 for _ in range(60):
  cs=m.containers()
  try:
   for c in cs:
    rs=m.control(c,'snapshot')['processes']
    assert {'backend','gateway'}<={r['role'] for r in rs}
    for r in rs:
     if r['role']=='backend':assert m.control(c,'backend-ready',runtime=r).get('ok') is True
   return cs
  except (MaintenanceError,AssertionError):time.sleep(1)
 raise AssertionError('real backend readiness')
class FaultTransport(ManagedMaintenance):
 def __init__(self,fault):super().__init__();self.fault=fault;self.dropped=False;self.recoveryDenied=False
 def control(self,c,action,**kw):
  result=super().control(c,action,**kw)
  if action=='backend' and kw.get('verb')=='commit' and not self.dropped:
   assert result.get('ok') is True
   assert any(r.get('commitIntent') for r in self.read()['runtimes'])
   self.dropped=True
   if self.fault=='crash':os._exit(86)
   if self.fault=='drop':raise MaintenanceError('injected_lost_real_commit_reply')
  if action=='backend-ready' and (self.root/'resume.json').exists():
   result_cli=sp.run(['docker','exec','-u','1000',c['id'],'hermes','--version'],capture_output=True)
   assert result_cli.returncode==75,'independent launch crossed recovery fence'
   try:self.enter();raise AssertionError('operation crossed recovery fence')
   except MaintenanceError:pass
   self.recoveryDenied=True
  return result
m=ManagedMaintenance();assert m.read() is None and not (m.root/'resume.json').exists();ready(m)
# Both failures happen after the real server has irreversibly committed.
for fault in ['drop','crash']:
 token=str(uuid.uuid4());fm=FaultTransport(fault)
 before={(c['name'],r['pid'],r['start']) for c in fm.containers() for r in fm.control(c,'snapshot')['processes'] if r['role']=='backend'}
 if fault=='drop':
  try:fm.acquire(token);raise AssertionError('injection not exercised')
  except MaintenanceError as e:assert str(e)=='injected_lost_real_commit_reply',str(e)
  assert fm.recoveryDenied
 else:
  pid=os.fork()
  if pid==0:fm.acquire(token);os._exit(99)
  assert os.waitpid(pid,0)[1]>>8==86
  lease=m.read();assert lease and any(r.get('commitIntent') and not r.get('committed') for r in lease['runtimes'])
  try:m.release(str(uuid.uuid4()));raise AssertionError('wrong owner admitted')
  except MaintenanceError as e:assert str(e)=='maintenance_token_mismatch'
  fm=FaultTransport(None);assert fm.release(token)['ok'];assert fm.recoveryDenied
 ready(m);assert m.read() is None and not (m.root/'resume.json').exists()
 after={(c['name'],r['pid'],r['start']) for c in m.containers() for r in m.control(c,'snapshot')['processes'] if r['role']=='backend'}
 assert before!=after
 save('real_backend_'+fault+'_commit_response_recovers',replacementObserved=True,recoveryAdmissionDenied=True)
# Real synthetic import/undo: the VM itself is the disposable used-disk clone.
script='/opt/wizard/bin/wizard-import-hermes';data=Path('/home/wizard/runtipi/app-data/wizardapps/hermes-agent/data');soul=data/'SOUL.md'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
before={x:digest(data/x) for x in ['SOUL.md','.env','auth.json']}
z=a.output/'synthetic-import.zip'
with zipfile.ZipFile(z,'w') as f:f.writestr('SOUL.md','# Synthetic Recovery QA\n\nThis is a disposable import proof.\n')
token=str(uuid.uuid4());assert m.acquire(token)['phase']=='held'
try:
 result=sp.run([script,'file',str(z)],capture_output=True,text=True,timeout=30)
 payload=json.loads(result.stdout);assert result.returncode!=0 and payload['error']=='maintenance_active'
 assert before=={x:digest(data/x) for x in before};save('real_import_refused_during_update_before_mutation')
finally:m.release(token)
proc=sp.Popen([script,'file',str(z)],stdout=sp.PIPE,stderr=sp.PIPE,text=True)
try:
 for _ in range(100):
  if m.operation_busy():break
  assert proc.poll() is None;time.sleep(.05)
 else:raise AssertionError('import never held reservation')
 try:m.acquire(str(uuid.uuid4()));raise AssertionError('update admitted during import')
 except MaintenanceError as e:assert str(e)=='operation_in_flight',str(e)
 out,err=proc.communicate(timeout=240);payload=json.loads(out)
 assert proc.returncode==0 and payload['ok'],{'exit':proc.returncode,'error':payload.get('error'),'rollback':payload.get('rolled_back',{}).get('ok')}
 assert soul.read_text().startswith('# Synthetic Recovery QA');save('real_guarded_import_with_owned_operation')
finally:
 if proc.poll() is None:proc.wait(timeout=240)
result=sp.run([script,'undo'],capture_output=True,text=True,timeout=240);payload=json.loads(result.stdout)
assert result.returncode==0 and payload['ok'],{'exit':result.returncode,'error':payload.get('error')}
assert before=={x:digest(data/x) for x in before};ready(m);assert not m.operation_busy()
save('real_guarded_undo_restores_identity_and_auth_hashes',hashesEqual=True)
z.unlink()
