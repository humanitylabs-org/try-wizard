#!/usr/bin/env python3
"""Actual runtime TLS checks, also fed on stdin into each discovered interpreter.
A DNS error, proxy block, timeout or HTTP failure is never certificate rejection.
"""
import concurrent.futures, hashlib, time, json, os, re, shutil, ssl, subprocess, sys, urllib.error, urllib.request
from pathlib import Path
BAD=[kind+'-'+suffix+'-emudhra' for suffix in ['g3b','g3c','g3b-aaa','g3c-aaa'] for kind in ['dv','ov','ev']]+['dv-g3b-noct-emudhra','dv-g3b-aaa-noct-emudhra']
GOOD=['https://example.com/','https://probe-emudhra.we-have-a-problem.com/']
ROOTS=['/opt','/app','/usr/local/lib','/usr/lib','/home/wizard','/root']
MIN_NODE={22:(22,23,4),24:(24,22,1),26:(26,12,1)}

def version(text):
    match=re.search(r'(\d+)\.(\d+)\.(\d+)',text);assert match, text
    return tuple(map(int,match.groups()))
def node_supported(text):
    v=version(text);return v[0] in MIN_NODE and v>=MIN_NODE[v[0]]
def files():
    for root in ROOTS:
        for parent,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','__pycache__'}]
            if Path(parent).name=='certifi' and 'cacert.pem' in names:yield Path(parent)/'cacert.pem'

def python_checks():
    ctxs=[('system',ssl.create_default_context())];seen=set()
    for name in ['REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS']:
        if os.environ.get(name):ctxs.append((name+':'+os.environ[name],ssl.create_default_context(cafile=os.environ[name])))
    for f in files():
        # Version is read from actual package source, including pip._vendor copies.
        raw=(f.parent/'__init__.py').read_text()
        m=re.search(r'__version__\s*=\s*[\'"]([^\'"]+)',raw)
        assert m and tuple(map(int,m[1].split('.')))>=(2026,10,19),str(f)
        key=hashlib.sha256(f.read_bytes()).hexdigest()
        if key not in seen:ctxs.append((str(f),ssl.create_default_context(cafile=str(f))));seen.add(key)
    def request(row):
        name,ctx,url,bad=row
        # Retry only transport failures (EOF, bad record MAC, resets, timeouts); an accepted chain fails at once.
        for attempt in range(3):
            try:return attempt_request(name,ctx,url,bad)
            except AssertionError as e:
                detail=e.args[0] if e.args else None
                transient=bad and isinstance(detail,tuple) and str(detail[-1]).startswith('<urlopen error') and 'CERTIFICATE_VERIFY_FAILED' not in str(detail[-1])
                if not transient or attempt==2:raise
                time.sleep(2)
    def attempt_request(name,ctx,url,bad):
        try:
            with urllib.request.urlopen(url,context=ctx,timeout=20) as r:
                body=r.read(4096)
                assert not bad,'compromised chain accepted: '+url
                assert r.status==200
                if 'probe-emudhra' in url:assert b'Your client successfully connected to the site.' in body
        except urllib.error.URLError as e:
            assert bad and isinstance(e.reason,ssl.SSLCertVerificationError),(name,url,str(e))
        return {'context':name,'url':url,'certificateRejected':bad}
    tasks=[(n,c,u,False) for n,c in ctxs for u in GOOD]+[(n,c,'https://'+h+'.we-have-a-problem.com/',True) for n,c in ctxs for h in BAD]
    # 4 concurrent handshakes measured clean on Thales/Colima; 8 corrupted 14/64.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:checks=list(pool.map(request,tasks))
    # Python's incident release only upgrades bundled pip/certifi. Every ensurepip bootstrap
    # wheel must carry that real fix too; old wheels could recreate a vulnerable environment later.
    import zipfile
    for root in ROOTS:
        for parent,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','__pycache__'}]
            if Path(parent).name=='_bundled' and Path(parent).parent.name=='ensurepip':
                wheels=[Path(parent)/n for n in names if n.startswith('pip-') and n.endswith('.whl')]
                assert len(wheels)==1 and wheels[0].name=='pip-26.2.2-py3-none-any.whl',parent
                with zipfile.ZipFile(wheels[0]) as archive:
                    raw=archive.read('pip/_vendor/certifi/__init__.py')
                    assert b'2026.10.19' in raw,(parent,raw)
    print(json.dumps({'python':sys.executable,'version':sys.version,'contexts':[n for n,_ in ctxs],'checks':checks}))

class _CDP:
    """Chrome DevTools over --remote-debugging-pipe (fds 3/4); stdlib only. headless-shell 155 no longer honours --dump-dom."""
    def __init__(self,binary):
        import tempfile
        r1,w1=os.pipe();r2,w2=os.pipe()  # r1->chrome fd3 (commands), w2<-chrome fd4 (responses)
        self.dir=tempfile.mkdtemp()
        # close_fds runs after preexec_fn, so pass_fds keeps the remapped 3/4.
        def fds():
            a,b=os.dup(r1),os.dup(w2);os.dup2(a,3);os.dup2(b,4)  # temp copies: r1/w2 may already be 3 or 4
        self.proc=subprocess.Popen([binary,'--headless','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-first-run','--user-data-dir='+self.dir,'--remote-debugging-pipe','about:blank'],preexec_fn=fds,pass_fds=(3,4),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        os.close(r1);os.close(w2);self.w=os.fdopen(w1,'wb');self.r=os.fdopen(r2,'rb');self.n=0;self.buf=b''
    def call(self,method,params=None,session=None,timeout=40):
        import select,time
        self.n+=1;msg={'id':self.n,'method':method,'params':params or {}}
        if session:msg['sessionId']=session
        self.w.write(json.dumps(msg).encode()+b'\0');self.w.flush();end=time.time()+timeout
        while True:
            while b'\0' in self.buf:
                raw,self.buf=self.buf.split(b'\0',1);obj=json.loads(raw)
                if obj.get('id')==self.n:
                    assert 'error' not in obj,(method,obj['error']);return obj['result']
            left=end-time.time();assert left>0,('cdp timeout',method)
            ready,_,_=select.select([self.r],[],[],left)
            if ready:
                chunk=os.read(self.r.fileno(),65536);assert chunk,'chrome exited'
                self.buf+=chunk
    def close(self):
        try:self.proc.kill();self.proc.wait(10)
        finally:shutil.rmtree(self.dir,ignore_errors=True)

def _visit(cdp,url):
    import time
    target=cdp.call('Target.createTarget',{'url':'about:blank'})['targetId']
    session=cdp.call('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
    nav=cdp.call('Page.navigate',{'url':url},session,timeout=40)
    text=''
    if not nav.get('errorText'):
        for _ in range(40):
            res=cdp.call('Runtime.evaluate',{'expression':'document.readyState+"|"+(document.body?document.body.innerText:"")','returnByValue':True},session)
            text=res['result'].get('value','')
            if text.startswith('complete|'):break
            time.sleep(.5)
    cdp.call('Target.closeTarget',{'targetId':target})
    return nav.get('errorText',''),text

def browser_checks():
    # Chrome has its own trust path; curl success is never browser evidence.
    paths=[shutil.which(n) for n in ['headless-shell','headless_shell','chromium','chromium-browser','google-chrome']]
    paths += [str(p) for p in [Path('/headless-shell/headless-shell'),Path('/headless-shell/headless_shell')] if p.is_file()]
    binaries=sorted({str(Path(p).resolve()) for p in paths if p})
    for binary in binaries:
        cdp=_CDP(binary)
        try:
            for host,bad in [('probe-emudhra.we-have-a-problem.com',False)]+[(h+'.we-have-a-problem.com',True) for h in BAD]:
                error,text=_visit(cdp,'https://'+host+'/')
                if not bad:assert not error and 'Your client successfully connected to the site.' in text,(binary,host,error,text[:200])
                else:
                    assert 'Your client successfully connected to the site.' not in text,(binary,host,'compromised chain accepted')
                    assert re.search(r'ERR_CERT_|ERR_CERTIFICATE_',error),(binary,host,'network failure is not certificate rejection',error)
                print(json.dumps({'browser':binary,'host':host,'certificateRejected':bad,'netError':error}))
        finally:cdp.close()

def main():
    python_checks()
    browser_checks()

if __name__=='__main__':main()
