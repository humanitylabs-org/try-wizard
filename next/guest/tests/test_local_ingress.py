#!/usr/bin/env python3
"""Run the actual ingress config with disposable HTTP upstreams, never a VM."""
import http.client,http.server,pathlib,socket,subprocess,tempfile,threading,time,unittest
CONFIG=pathlib.Path(__file__).parents[1]/'overlay/opt/wizard/local-proxy.conf'
class Upstream(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(self.headers.get('Tailscale-User-Login','').encode())
 def log_message(self,*args):pass
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
 def test_exact_authorities_before_owner_injection(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td)
   upstream=http.server.ThreadingHTTPServer(('127.0.0.1',0),Upstream)
   threading.Thread(target=upstream.serve_forever,daemon=True).start()
   with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
   text=CONFIG.read_text().replace('/run/wizard-local-proxy.pid',str(root/'nginx.pid')).replace('127.0.0.1:8924',f'127.0.0.1:{port}').replace('127.0.0.1:8796',f'127.0.0.1:{upstream.server_port}').replace('127.0.0.1:8798',f'127.0.0.1:{upstream.server_port}')
   (root/'nginx.conf').write_text(text)
   process=subprocess.Popen(['/opt/homebrew/bin/nginx','-p',td,'-c',str(root/'nginx.conf'),'-g','daemon off;'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   try:
    for _ in range(80):
     try:
      with socket.create_connection(('127.0.0.1',port),timeout=.1):break
     except OSError:time.sleep(.05)
    def request(host,path='/wizard/v1/agents'):
     c=http.client.HTTPConnection('127.0.0.1',port,timeout=2);c.request('GET',path,headers={'Host':host});r=c.getresponse();out=(r.status,r.read());c.close();return out
    for host in ['attacker.test','attacker.test:48023','127.0.0.1','127.0.0.1:9999','localhost:9999','[::1]:48023']:
     self.assertEqual(request(host)[0],421,host)
    self.assertEqual(request('127.0.0.1:48023'),(200,b'owner@wizard.local'))
    self.assertEqual(request('localhost:48023')[0],404)
    self.assertEqual(request('localhost:48023','/apps/test/'),(200,b'owner@wizard.local'))
   finally:
    process.terminate();process.communicate(timeout=5);upstream.shutdown();upstream.server_close()
if __name__=='__main__':unittest.main()
