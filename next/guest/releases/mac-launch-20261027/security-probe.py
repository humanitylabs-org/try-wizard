#!/usr/bin/env python3
"""Actual runtime TLS checks, also fed on stdin into each discovered interpreter.
A DNS error, proxy block, timeout or HTTP failure is never certificate rejection.
"""
import concurrent.futures, hashlib, json, os, re, shutil, ssl, subprocess, sys, urllib.error, urllib.request
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:checks=list(pool.map(request,tasks))
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

def browser_checks():
    # Chrome has its own trust path; curl success is never browser evidence.
    paths=[shutil.which(n) for n in ['headless-shell','headless_shell','chromium','chromium-browser','google-chrome']]
    paths += [str(p) for p in [Path('/headless-shell/headless-shell'),Path('/headless-shell/headless_shell')] if p.is_file()]
    binaries=sorted({str(Path(p).resolve()) for p in paths if p})
    for binary in binaries:
        for host,bad in [('probe-emudhra.we-have-a-problem.com',False)]+[(h+'.we-have-a-problem.com',True) for h in BAD]:
            proc=subprocess.run([binary,'--headless','--no-sandbox','--disable-dev-shm-usage','--dump-dom','https://'+host+'/'],capture_output=True,text=True,timeout=40)
            assert proc.returncode==0,(binary,host,proc.stderr)
            if not bad:assert 'Your client successfully connected to the site.' in proc.stdout,(binary,host,proc.stderr)
            else:
                assert 'Your client successfully connected to the site.' not in proc.stdout,(binary,host,'compromised chain accepted')
                assert re.search(r'ERR_CERT_|ERR_CERTIFICATE_|net_error -20[0-9]',proc.stdout+proc.stderr),(binary,host,'network failure is not certificate rejection',proc.stderr)
            print(json.dumps({'browser':binary,'host':host,'certificateRejected':bad}))

def main():
    python_checks()
    browser_checks()

if __name__=='__main__':main()
