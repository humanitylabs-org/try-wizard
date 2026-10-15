#!/usr/bin/env python3
"""Root-only packaging controller. Stock modules are imported, never altered.
Input/output are private control messages. Never return credentials or prompts.
"""
import fcntl,http.cookiejar,json,os,signal,socket,sys,time,urllib.request,urllib.error
from pathlib import Path
STATE=Path('/wizard-managed-state');HOST=socket.gethostname()
def identity(pid):
 p=Path('/proc')/str(pid);s=(p/'stat').read_text();return s[s.rindex(')')+2:].split()[19]
def locked(pid):
 try:
  with (STATE/'launch'/f'{HOST}-{pid}').open() as f:
   try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);return False
   except BlockingIOError:return True
 except FileNotFoundError:return False
def snapshot():
 rows=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit() or int(p.name)==os.getpid():continue
  try:
   args=(p/'cmdline').read_bytes().decode().split('\0')[:-1]
   if not args or not Path(args[0]).name.startswith('python'):continue
   # Linux ptrace rules also protect /proc from uid-0 without CAP_SYS_PTRACE.
   # Read only this process's metadata as its actual owner, then restore root.
   uid=p.stat().st_uid;gid=p.stat().st_gid
   try:
    os.setegid(gid);os.seteuid(uid)
    exe=(p/'exe').readlink().as_posix()
    env=dict(x.split('=',1) for x in (p/'environ').read_bytes().decode().split('\0') if '=' in x)
   finally:os.seteuid(0);os.setegid(0)
   role='session'
   # Only exact stock supervised daemon commands receive cooperative retirement.
   if '/opt/hermes/.venv/bin/hermes' in args:
    at=args.index('/opt/hermes/.venv/bin/hermes');rest=args[at+1:]
    if rest[:2]==['gateway','run']:role='gateway'
    elif rest and rest[0] in ['dashboard','serve']:role='backend'
   rows.append({'pid':int(p.name),'start':identity(p.name),'managed':locked(p.name),'role':role,'home':env.get('HERMES_HOME','/opt/data')})
  except (FileNotFoundError,ProcessLookupError):continue
 return rows
def live(row):
 try:return identity(row['pid'])==row['start']
 except (FileNotFoundError,ProcessLookupError):return False

def client():
 port=os.environ.get('HERMES_DASHBOARD_PORT','9119');base='http://127.0.0.1:'+port
 jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
 def request(path,body=None):
  req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
  try:
   with opener.open(req,timeout=10) as response:return json.load(response)
  except urllib.error.HTTPError as e:raise RuntimeError('backend_http_'+str(e.code)+'_'+path.replace('/','_')) from None
 user=os.environ.get('HERMES_DASHBOARD_BASIC_AUTH_USERNAME');password=os.environ.get('HERMES_DASHBOARD_BASIC_AUTH_PASSWORD')
 if not user or not password:raise RuntimeError('backend_auth_contract_unknown')
 request('/auth/password-login',{'provider':'basic','username':user,'password':password})
 return request

def main(req):
 action=req['action']
 if action=='snapshot':return {'processes':snapshot()}
 if action=='clear-drain':
  os.environ['HERMES_HOME']=req['home']
  from gateway.drain_control import clear_drain_request
  clear_drain_request();return {'ok':True}
 if action=='gateway':
  row=req['runtime'];assert live(row),'runtime_changed'
  os.environ['HERMES_HOME']=row['home']
  from gateway.control_socket import query_gateway_control
  verb=req['verb']
  if verb in ['drain','cancel']:
   # Identical supported file contract to POST /api/gateway/drain, per home.
   from gateway.drain_control import write_drain_request,clear_drain_request
   if verb=='drain':write_drain_request(principal='wizard-managed-update',suppress_notification=True)
   else:clear_drain_request()
   return {'ok':True}
  assert verb in ['status','pause-for-update','identify']
  result=query_gateway_control(Path(row['home']),verb,timeout=5)
  if result is None:raise RuntimeError('gateway_ack_unknown')
  return result
 if action=='backend':return client()('/api/health/retirement/'+req['verb'],req.get('body',{}))
 if action=='stop-backend':
  row=req['runtime'];assert row['role']=='backend'
  if live(row):os.kill(row['pid'],signal.SIGTERM)
  for _ in range(100):
   if not live(row):return {'ok':True}
   time.sleep(.1)
  raise RuntimeError('backend_did_not_exit')
 raise RuntimeError('unknown_control_action')
if __name__=='__main__':
 try:print(json.dumps(main(json.load(sys.stdin))))
 except Exception as e:
  print(json.dumps({'error':str(e) if isinstance(e,RuntimeError) else type(e).__name__}));sys.exit(1)
