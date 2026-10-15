#!/usr/bin/env python3
"""Actual owned-guest runtime acceptance. No real-person content/credentials logged."""
import hashlib,json,os,subprocess,time,urllib.request,urllib.error,uuid
from pathlib import Path
R=Path('/mnt/stack');E=R/os.environ.get('GUEST_EVIDENCE','evidence-existing');E.mkdir(exist_ok=True)
report={'schema':1,'kind':'real-arm64-guest-runtime','checks':{},'gates':{'private_inference':'unconfigured Tinfoil, refused without fallback','phone_enrollment':'not activated','builder':'separate owner deferred','optional_apps':'not accepted'}}
def check(k,v):
 report['checks'][k]=v
 (E/'runtime-acceptance.json').write_text(json.dumps(report,indent=2))
 assert v,k

def api(path,body=None,method=None,headers=None,base='http://127.0.0.1:8924'):
 h={'Content-Type':'application/json'};h.update(headers or {})
 data=body if isinstance(body,bytes) else None if body is None else json.dumps(body).encode()
 req=urllib.request.Request(base+path,data=data,headers=h,method=method)
 try:r=urllib.request.urlopen(req,timeout=180)
 except urllib.error.HTTPError as e:r=e
 raw=r.read()
 try:d=json.loads(raw)
 except ValueError:d=raw.decode(errors='replace')
 return r.status,d,dict(r.headers)
def wait():
 for i in range(60):
  try:
   if api('/wizard/health')[0]==200:return
  except OSError:pass
  time.sleep(1)
 raise RuntimeError('Service restart health deadline')
def main():
 wait();check('bootstrap_uploads',api('/wizard/v1/bootstrap')[1]['capabilities']['resumable_uploads'])
 check('main_agent_running',api('/wizard/v1/agents')[1]['agents'][0]['status']=='running')
 body={'label':'Private','harness':'hermes','model':{'provider':'tinfoil','model':'glm-5-3'},'permissions':{'preset':'private'}}
 code,d,_=api('/wizard/v1/agents',body,headers={'Idempotency-Key':'release-private-r1'})
 check('private_provider_fail_closed',code in [200,201] and d['agent']['status_detail']=='provider_not_configured' and not d['agent']['model']['fallback'])
 code,bad,_=api('/wizard/v1/agents/private',{'model':{'provider':'anthropic','model':'claude-opus-5-5'}},method='PATCH')
 check('unconfigured_public_provider_rejected',code==400 and bad['check']=='agent.model.provider')
 code,bad,_=api('/wizard/v1/agents/private',{'model':{'provider':'tinfoil','model':'glm-5-3','fallback':True}},method='PATCH')
 check('private_fallback_rejected',code==409 and bad['check']=='agent.fallback')
 home=Path('/home/wizard/runtipi/app-data/wizard-os/agents/private/home')
 check('private_no_main_credentials',not (home/'auth.json').exists() and not (home/'state.db').exists())
 # No app package is invented: register a declared QA app solely to exercise real binding and stock DB delivery.
 apps=Path('/home/wizard/runtipi/app-data/wizard-os/apps.json');original=apps.read_bytes();doc=json.loads(original)
 qa={'id':'release-qa','name':'Release acceptance fixture','status':'running','agent_binding':{'required':True,'purpose':'QA delivery'}}
 doc['apps'].append(qa);apps.write_text(json.dumps(doc));time.sleep(2)
 try:
  code,binding,_=api('/wizard/v1/apps/release-qa/binding');check('binding_default_main',code==200 and binding['binding']['agent']=='hermes')
  # Only this newly-created fixture token is read in memory, never printed or exported.
  token=Path('/home/wizard/runtipi/app-data/wizardapps/wizard-shell/data/wizard-os/app-tokens/release-qa').read_text().strip()
  payload={'delivery_key':'release-real-'+uuid.uuid4().hex,'title':'Release QA receipt','body':'Synthetic runtime delivery probe.','thread':'acceptance'}
  base='http://172.19.0.1:7797';path='/wizard/v1/apps/release-qa/deliveries'
  check('machine_control_isolated',api('/wizard/v1/agents',base=base)[0]==404)
  check('machine_delivery_auth',api(path,payload,base=base)[0]==403)
  check('machine_delivery_browser_rejected',api(path,payload,headers={'Authorization':'Bearer '+token,'Origin':'null'},base=base)[0]==403)
  code,d,_=api(path,payload,headers={'Authorization':'Bearer '+token},base=base)
  (E/'binding-delivery.json').write_text(json.dumps({'status':code,'receipt':d},indent=2))
  check('real_stock_binding_delivery',code==200 and d.get('verified') is True)
  replay=api(path,payload,headers={'Authorization':'Bearer '+token},base=base)
  check('delivery_idempotent',replay[0]==200 and replay[1]['already_delivered'])
 finally:apps.write_bytes(original)
 # Durable uploads survive an actual Service container restart midway, then complete into shared Files.
 data=os.urandom(3*1024*1024+7);digest=hashlib.sha256(data).hexdigest();key=uuid.uuid4().hex
 code,u,_=api('/wizard/v1/uploads',{'client_upload_id':key,'filename':'release-'+key+'.bin','mime':'application/octet-stream','bytes':len(data),'sha256':digest,'destination':{'folder':'Documents'}})
 check('upload_create',code==201);path='/wizard/v1/uploads/'+u['upload_id'];split=1024*1024
 check('upload_chunk',api(path,data[:split],method='PATCH',headers={'Content-Type':'application/offset+octet-stream','Upload-Offset':'0'})[0]==204)
 subprocess.run(['docker','restart','wizard-shell_wizardapps-wizard-shell-1'],check=True,stdout=subprocess.DEVNULL);wait()
 check('upload_resume_after_restart',api(path)[1]['offset']==split)
 check('upload_stale_offset_rejected',api(path,b'x',method='PATCH',headers={'Content-Type':'application/offset+octet-stream','Upload-Offset':'0'})[0]==409)
 check('upload_remainder',api(path,data[split:],method='PATCH',headers={'Content-Type':'application/offset+octet-stream','Upload-Offset':str(split)})[0]==204)
 code,done,_=api(path+'/complete',{});check('upload_complete',code==200 and done['file']['sha256']==digest)
 file=Path('/home/wizard/runtipi/media')/done['file']['path'];check('user_files_bytes',hashlib.sha256(file.read_bytes()).hexdigest()==digest)
 check('upload_completion_idempotent',api(path+'/complete',{})[1]['file']['path']==done['file']['path'])
 check('upload_traversal_rejected',api('/wizard/v1/uploads',{'client_upload_id':key+'-bad','filename':'x','bytes':1,'destination':{'folder':'../outside'}})[0]==400)
 check('app_origin_control_denied',api('/wizard/v1/agents',headers={'Host':'localhost:48023'})[0]==404)
 # Match shipped critical source bytes from the running container, not just an image label.
 for rel in ['server/agents.mjs','server/uploads.mjs','server/service.mjs','ux/core/chat-models.js']:
  live=subprocess.check_output(['docker','exec','wizard-shell_wizardapps-wizard-shell-1','sha256sum','/app/'+rel],text=True).split()[0]
  src=R/('ux/web/'+rel[3:] if rel.startswith('ux/') else 'service/'+rel)
  check('served_source_'+rel,live==hashlib.sha256(src.read_bytes()).hexdigest())
 report['completed']=True;(E/'runtime-acceptance.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
