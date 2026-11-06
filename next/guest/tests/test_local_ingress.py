#!/usr/bin/env python3
"""Run the actual ingress config with disposable HTTP upstreams, never a VM."""
import http.client,http.server,importlib.machinery,importlib.util,json,pathlib,shutil,socket,subprocess,tempfile,threading,time,unittest
GUEST=pathlib.Path(__file__).parents[1]
CONFIG=GUEST/'overlay/opt/wizard/local-proxy.conf'
OWNER_INC=GUEST/'overlay/opt/wizard/local-proxy-owner.inc'
ROUTES=GUEST/'overlay/opt/wizard/bin/wizard-local-routes'
NGINX=shutil.which('nginx') or '/opt/homebrew/bin/nginx'
def load_routes():
 loader=importlib.machinery.SourceFileLoader('wizard_local_routes',str(ROUTES))
 spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m);return m
class Upstream(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers()
  self.wfile.write(json.dumps({'port':self.server.server_port,'path':self.path,'login':self.headers.get('Tailscale-User-Login',''),'fwd':self.headers.get('X-Forwarded-For','')}).encode())
 def log_message(self,*args):pass
def serve():
 s=http.server.ThreadingHTTPServer(('127.0.0.1',0),Upstream);threading.Thread(target=s.serve_forever,daemon=True).start();return s
class Routes(unittest.TestCase):
 def setUp(self):self.m=load_routes()
 def test_owner_is_the_nodes_tailnet_login(self):
  status={'Self':{'UserID':7},'User':{'7':{'LoginName':'owner@example.com'},'8':{'LoginName':'other@example.com'}}}
  self.assertEqual(self.m.owner_login(status),'owner@example.com')
  self.assertEqual(self.m.owner_login({}),'')
  self.assertEqual(self.m.owner_login({'Self':{'UserID':7},'User':{'7':{'LoginName':'a";b'}}}),'')
 def test_only_the_shell_ports_box_local_handlers(self):
  serve={'Web':{'wizard.example-tailnet.ts.net:8796':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8796'},'/files/':{'Proxy':'http://127.0.0.1:8794/files/'},
   '/wizard-os-home/store-install':{'Proxy':'http://127.0.0.1:7791'},'/far/':{'Proxy':'http://203.0.113.9:80'},'/bad path/':{'Proxy':'http://127.0.0.1:1'}}},
   'wizard.example-tailnet.ts.net:8799':{'Handlers':{'/x/':{'Proxy':'http://127.0.0.1:8799'}}}}}
  self.assertEqual(self.m.handlers(serve,8796),[('/wizard-os-home/store-install','http://127.0.0.1:7791'),('/files/','http://127.0.0.1:8794/files/')])
class Ingress(unittest.TestCase):
 def test_setup_shell_uses_public_authority_not_transport_port(self):
  import ast, asyncio
  from urllib.parse import urlsplit
  tree=ast.parse((CONFIG.parent/'setup/server.py').read_text())
  function=next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='shell')
  namespace={'Any':object,'urlsplit':urlsplit,'PUBLIC_UX_ORIGIN':'http://127.0.0.1:48023','SHELL_ORIGIN':'http://127.0.0.1:8924'}
  calls=[]
  async def request(*args):calls.append(args);return (200,{'ok':True})
  namespace['_request']=request
  exec(compile(ast.Module(body=[function],type_ignores=[]),'<production-shell>','exec'),namespace)
  asyncio.run(namespace['shell']('GET','/wizard/v1/agents'))
  self.assertEqual(calls[0][1],'http://127.0.0.1:8924/wizard/v1/agents')
  self.assertEqual(calls[0][3]['Host'],'127.0.0.1:48023')
 @unittest.skipUnless(pathlib.Path(NGINX).exists(),'nginx not installed')
 def test_exact_authorities_owner_injection_and_serve_paths(self):
  m=load_routes()
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);run=root/'run';run.mkdir()
   shell,store,files=serve(),serve(),serve()
   with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
   rows=m.handlers({'Web':{'box.example-tailnet.ts.net:8796':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8796'},
    '/wizard-os-home/store-install':{'Proxy':f'http://127.0.0.1:{store.server_port}'},'/files/':{'Proxy':f'http://127.0.0.1:{files.server_port}/files/'}}}}},8796)
   (run/'routes.conf').write_text(''.join(m.location(a,b) for a,b in rows).replace('/opt/wizard/local-proxy-owner.inc',str(root/'owner.inc')))
   (run/'owner.conf').write_text('proxy_set_header Tailscale-User-Login "owner@example.com";\n')
   (run/'shell.conf').write_text(f'set $wz_shell http://127.0.0.1:{shell.server_port};\n')
   (root/'owner.inc').write_text(OWNER_INC.read_text().replace('/run/wizard-local-proxy/',f'{run}/'))
   text=(CONFIG.read_text().replace('/run/wizard-local-proxy.pid',str(root/'nginx.pid')).replace('user root root;','')
    .replace('/run/wizard-local-proxy/',f'{run}/').replace('/opt/wizard/local-proxy-owner.inc',str(root/'owner.inc'))
    .replace('127.0.0.1:8924',f'127.0.0.1:{port}').replace('127.0.0.1:8798',f'127.0.0.1:{shell.server_port}'))
   (root/'nginx.conf').write_text(text)
   process=subprocess.Popen([NGINX,'-p',td,'-c',str(root/'nginx.conf'),'-g','daemon off;'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   try:
    for _ in range(80):
     try:
      with socket.create_connection(('127.0.0.1',port),timeout=.1):break
     except OSError:time.sleep(.05)
    def request(host,path='/wizard/v1/agents',headers=None):
     c=http.client.HTTPConnection('127.0.0.1',port,timeout=2);c.request('GET',path,headers={'Host':host,**(headers or {})});r=c.getresponse();out=(r.status,r.read());c.close()
     return out[0],(json.loads(out[1]) if out[0]==200 else None)
    for host in ['attacker.test','attacker.test:48023','127.0.0.1','127.0.0.1:9999','localhost:9999','[::1]:48023']:
     self.assertEqual(request(host)[0],421,host)
    st,body=request('127.0.0.1:48023',headers={'Tailscale-User-Login':'attacker@example.com','X-Forwarded-For':'203.0.113.9'})
    self.assertEqual((st,body['port'],body['login'],body['fwd']),(200,shell.server_port,'owner@example.com',''))
    st,body=request('127.0.0.1:48023','/wizard-os-home/store-install/_updates?x=1')
    self.assertEqual((body['port'],body['path'],body['login']),(store.server_port,'/_updates?x=1','owner@example.com'))
    self.assertEqual(request('127.0.0.1:48023','/wizard-os-home/store-install')[1]['path'],'/')
    self.assertEqual(request('127.0.0.1:48023','/wizard-os-home/store-installer')[1]['port'],shell.server_port)
    st,body=request('127.0.0.1:48023','/files/a/b.txt')
    self.assertEqual((body['port'],body['path']),(files.server_port,'/files/a/b.txt'))
    self.assertEqual(request('localhost:48023')[0],404)
    st,body=request('localhost:48023','/apps/test/')
    self.assertEqual((st,body['login']),(200,'owner@example.com'))
   finally:
    process.terminate();process.communicate(timeout=5)
    for s in (shell,store,files):s.shutdown();s.server_close()
if __name__=='__main__':unittest.main()
