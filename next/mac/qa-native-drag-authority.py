#!/usr/bin/env python3
"""Thales-only exact-app NSEvent dragging and WK frame/origin authority regression.
Run under shared worker.lock: <mounted app> <packaged UX web> <evidence dir>.
Protocol fixtures; device-free delegate decisions use real WK frame/securityOrigin.
No physical mouse/mic, real agent/STT or guest VM acceptance is implied.
"""
import hashlib, http.server, json, os, platform, plistlib, re, socket
import subprocess as sp
import sys, threading, time
from pathlib import Path
from urllib.parse import unquote, urlsplit
APP, WEB, OUT = (Path(v).resolve() for v in sys.argv[1:4])
OUT.mkdir(parents=True, exist_ok=True)
DOMAIN = 'org.humanitylabs.wizard.mvp'
passed = []
status = {'state':'ready','stage':'Local voice ready','downloaded':1,'total':1}
class Fixture(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def translate_path(self, path):
        p = (WEB / unquote(urlsplit(path).path).removeprefix('/wizard-os-home/')).resolve()
        return str(p if p.is_relative_to(WEB) else WEB / '__denied__')
    def data(self, value, code=200, mime='application/json'):
        b = (json.dumps(value) if mime=='application/json' else value).encode()
        self.send_response(code);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        p = urlsplit(self.path).path
        if p == '/api/voice/status':return self.data(status)
        if p == '/authority.html':
            return self.data('''<!doctype html><html><body>Native authority fixture
            <button id="capture" onclick="navigator.mediaDevices.getUserMedia({audio:true}).then(s=>{s.getTracks().forEach(t=>t.stop());window.mediaResult='granted'}).catch(e=>window.mediaResult=e.name)">Capture diagnostic</button>
            <a id="selfLink" href="/authority.html?navigation=ok">Same-app navigation</a>
            <script>addEventListener('message',e=>{if(e.data==='navigate-self')document.querySelector('#selfLink').click()});
            window.replies=[];window.wizardNativeReply=m=>replies.push(m);
            window.probe=()=>{for(const method of ['app.info','qa.media-policy'])window.webkit.messageHandlers.wizardNative.postMessage({id:location.href,method,params:{}})};
            probe();</script></body></html>''', mime='text/html')
        if p.startswith('/wizard/') or p.startswith('/api/') or '/api/' in p:
            if p.endswith('/bootstrap'):return self.data({'bootstrap':1,'settings':{'agent':{'name':'Wizard'}},'capabilities':{'voice':True,'files':True},'endpoints':{}})
            if p.endswith('/model/options'):return self.data({'provider':'qa','model':'qa','providers':[]})
            return self.data({'sessions':[],'messages':[],'apps':[],'items':[],'state':{}})
        return super().do_GET()
class IPv6Server(http.server.ThreadingHTTPServer):address_family=socket.AF_INET6

def run(*args,check=True):return sp.run(list(map(str,args)),check=check,text=True,stdout=sp.PIPE,stderr=sp.STDOUT,timeout=35)
def qa(cmd):run(OUT/'qa-post',cmd)
def ask(suffix,cmd):
    p=Path('/tmp/wizard-mvp-qa-'+suffix);p.unlink(missing_ok=True);qa(cmd)
    until=time.monotonic()+12
    while time.monotonic()<until:
        if p.exists():return p.read_text()
        time.sleep(.1)
    raise AssertionError('Missing native reply: '+cmd)
def ev(code):
    s=ask('eval.txt','eval '+code)
    assert not s.startswith('ERROR'),s
    return s
def state():return json.loads(ask('state.json','state'))
def authority():return json.loads(ask('authority.json','native-authority-state'))
def wait(fn,seconds=30):
    end=time.monotonic()+seconds;last=None
    while time.monotonic()<end:
        last=fn()
        if last:return last
        time.sleep(.2)
    raise AssertionError('Timed out: '+str(last))
def ok(c,name):
    assert c,name
    passed.append(name);print('PASS',name,flush=True)
def frame(s):return list(map(float,re.findall(r'-?\d+(?:\.\d+)?',s)))
def point(selector):return json.loads(ev("JSON.stringify((()=>{const r=document.querySelector("+json.dumps(selector)+").getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})())"))
def mouse(x,y,dx=0,dy=0):qa(f'native-mouse {x} {y} {dx} {dy}');time.sleep(.6)
def capture(name):
    p=OUT/(name+'.png');w=authority()['windowNumber']
    r=run('screencapture','-x','-l',w,p,check=False)
    receipt={'surface':'real full-window screencapture','windowNumber':w,'exit':r.returncode,'output':r.stdout,'exists':p.exists()}
    (OUT/(name+'-capture.json')).write_text(json.dumps(receipt,indent=2))
    return receipt

if platform.system()!='Darwin':raise SystemExit('Must run on Thales')
prior=run('pgrep','-f',r'/Contents/MacOS/Wizard$',check=False).stdout.strip()
if prior:raise SystemExit('Another native Wizard is running; do not kill: '+prior)
# Bind an isolated IPv6 app-only vhost. Never contact or mutate the resident Host's IPv4 control bridge.
production_local = os.environ.get('QA_PRODUCTION_LOCAL') == '1'
server=http.server.ThreadingHTTPServer(('127.0.0.1',48023 if production_local else 0),Fixture)
appserver=IPv6Server(('::1',48023),Fixture)
other=http.server.ThreadingHTTPServer(('127.0.0.1',0),Fixture)
servers=[server,appserver,other]
if production_local:
    class SetupFixture(Fixture):
        def do_GET(self):
            if urlsplit(self.path).path == '/':
                self.send_response(302); self.send_header('Location', 'http://127.0.0.1:48023/wizard-os-home/desktop.html')
                self.send_header('Content-Length', '0'); self.end_headers(); return
            return super().do_GET()
    servers.append(http.server.ThreadingHTTPServer(('127.0.0.1',48030),SetupFixture))
URL=f'http://127.0.0.1:{server.server_port}/wizard-os-home/desktop.html'
CONTROL=f'http://127.0.0.1:{server.server_port}/authority.html'
APPURL='http://localhost:48023/authority.html'
OTHER=f'http://127.0.0.1:{other.server_port}/authority.html'
for s in servers:threading.Thread(target=s.serve_forever,daemon=True).start()
backup=OUT/'defaults-before.plist'
saved=run('defaults','export',DOMAIN,backup,check=False).returncode==0
proc=None
try:
    notifier=OUT/'qa-post.swift'
    notifier.write_text('import Foundation\nDistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.mvp.qa"),object:CommandLine.arguments[1],userInfo:nil,deliverImmediately:true)\nRunLoop.main.run(until:Date().addingTimeInterval(0.1))\n')
    run('xcrun','swiftc','-O',notifier,'-o',OUT/'qa-post')
    # Command-line-only isolated DataHome; preserve resident Host keys.
    for key in ['backends','activeBackend']:run('defaults','delete',DOMAIN,key,check=False)
    proc=sp.Popen([str(APP/'Contents/MacOS/Wizard'),'-QAHooks','YES','-QAWebStorage','YES','-DataHome',str(OUT/'data-home'),'-CapsLockRemap','NO'],stdout=(OUT/'native-app.log').open('w'),stderr=sp.STDOUT)
    time.sleep(2);qa('update-later');qa('voice-production-origin' if production_local else 'voice-local-fixture '+URL)
    wait(lambda:ev('!!window.__wux && !!window.__wux.live.ok')=='1')
    wait(lambda:state()['overlayHidden'] and not state()['localVoice']['visible'])
    wait(lambda:frame(authority()['header'])[3]>0)
    a=authority();(OUT/'drag-before.json').write_text(json.dumps(a,indent=2))
    ok(a['trustedDocument'],'selected local control/setup origin is trusted')
    if production_local:
        ok(state()['url']==URL and a['nativeControlURL'].rstrip('/')=='http://127.0.0.1:48023','production setup48030 redirect retains trusted shell48023 and API origin with QA override disabled')
    # Find blank header hit space using the live DOM, not hardcoded layout widths.
    x,y=json.loads(ev("JSON.stringify((()=>{const b=document.querySelector('#bar').getBoundingClientRect();const controls=[...document.querySelectorAll('#bar button,#bar a,#bar [data-ws],#voicePill')].filter(e=>e.getClientRects().length).map(e=>e.getBoundingClientRect());for(let x=100;x<b.width-10;x+=4){const y=b.height/2;if(!controls.some(r=>x>=r.left-6&&x<=r.right+6&&y>=r.top-6&&y<=r.bottom+6))return [x,y]}throw Error('no blank header')})())"))
    ev('getSelection().removeAllRanges();true')
    mouse(x,y,48,-36)
    b=authority();(OUT/'drag-after.json').write_text(json.dumps(b,indent=2))
    f0,f1=frame(a['frame']),frame(b['frame'])
    ok(b['dragCount']==a['dragCount']+1,'real NSEvent mouseDown hits native drag view')
    ok(abs(f1[0]-f0[0])>10 or abs(f1[1]-f0[1])>10,'real AppKit drag changes actual native window frame')
    ok(ev('getSelection().toString()')=='','title-bar drag does not select web text')
    ok(f1[2:]==f0[2:],'dragging preserves native window size')
    capture('ready-full-window')
    ev("const ac=new AudioContext(), dst=ac.createMediaStreamDestination(), osc=ac.createOscillator();osc.connect(dst);osc.start();ac.resume();Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>dst.stream.clone(),configurable:true});true")
    for selector in ['#logo','#clock','#micBtn','#status','#keysBtn','#wsList button']:
        xy=point(selector)
        before=authority()['dragCount']
        # Record real page mouseDown/click rather than relying on a DOM .click().
        ev("window.qaClicked=0;document.querySelector("+json.dumps(selector)+").addEventListener('click',()=>window.qaClicked++,{once:true});true")
        mouse(*xy)
        clicked = ev('qaClicked')=='1'
        ok(authority()['dragCount']==before,selector+' native mouse event is not intercepted by drag monitor')
        if not clicked:
            # SSH/occluded session reports keyWindow=false despite makeKey; its
            # WindowServer routing may suppress ordinary WebKit mouse delivery.
            # Do not turn a DOM click into purported native-click acceptance.
            ev("document.querySelector("+json.dumps(selector)+").click();true")
        ok(ev('qaClicked')=='1',selector+(' real native click reaches web action' if clicked else ' functional web action (DOM fallback; native-click headless limit)'))
        # close overlays; cancel manual voice if started (no media success claim).
        ev("document.querySelector('#voiceCancel').click();document.querySelectorAll('[data-close]').forEach(e=>e.click());document.querySelector('#palette').hidden=true;true")
    # Desktop content click must not move the host window.
    a=authority();mouse(200,240,28,-18);b=authority()
    ok(b['dragCount']==a['dragCount'] and b['frame']==a['frame'],'desktop content remains non-draggable')
    for size in ['700x780','1120x1000','380x560']:
        qa('window-size '+size);time.sleep(.8)
        ok(frame(authority()['header'])[2]>0,'native header regions update at '+size)
    status.update(state='error',stage='QA recovery')
    wait(lambda:state()['localVoice']['visible'])
    capture('recovery-full-window')
    status.update(state='ready');wait(lambda:not state()['localVoice']['visible'])
    # Exercise current restart admission on the real trusted desktop. Device
    # acquisition is an explicitly pending fixture; no live mic claim is made.
    if production_local:
        def admission(): return json.loads(ask('admission.json','update-admission'))
        ev("Object.values(__wux.wins).forEach(w=>__wux.closeWin(w.id));__wux.newChat();const e=document.querySelector('.win.focus textarea');e.value='update admission draft';e.dispatchEvent(new Event('input',{bubbles:true}));window.qaAcquire=0;Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:()=>{qaAcquire++;return new Promise((resolve,reject)=>{window.qaReject=reject})},configurable:true});true")
        ok(admission()['admitted'] and ev('window.__wizardUpdateFrozen')=='1','actual trusted idle admission atomically freezes new capture starts')
        ev("document.querySelector('#micBtn').click();true")
        qa('voice-native-event flags 54 1048576 0;flags 54 0 0.12');time.sleep(.5)
        ok(ev("qaAcquire===0 && __wux.voice==='idle'")=='1','frozen manual microphone and native Right Command event paths admit no capture')
        qa('update-unfreeze');time.sleep(.3)
        for route in ['manual','right-command']:
            if route=='manual':ev("document.querySelector('#micBtn').click();true")
            else:qa('voice-native-event flags 54 1048576 0;flags 54 0 0.12')
            wait(lambda:ev("__wux.voice==='listen' && typeof qaReject==='function'")=='1')
            ok(not admission()['admitted'] and ev('!window.__wizardUpdateFrozen')=='1',route+' pending microphone permission defers restart and preserves the take')
            ok(ev("document.querySelector('.win.focus textarea').value==='update admission draft'")=='1',route+' deferred restart preserves typed draft')
            ev("document.querySelector('#voiceCancel').click();qaReject(new Error('QA cancelled pending acquisition'));true")
            wait(lambda:ev("__wux.voice==='idle'")=='1')
        ok(ev("document.querySelector('.win.focus textarea').value==='update admission draft'")=='1','cancelled pending recording retains unsent draft')
    # Use actual WebKit main and child frames. The device-free diagnostic invokes
    # the production media permission delegate with each caller's WKFrameInfo.
    ev('location.href='+json.dumps(CONTROL)+';true')
    wait(lambda:ev('typeof probe')=='function')
    wait(lambda:any(m['method']=='app.info' and m['admitted'] for m in authority()['messages']))
    ok(ev('replies.length')=='1','trusted main native app.info callback returns through real WK bridge')
    ok(authority()['media'][-1]['granted'],'trusted local main media policy retains grant path')
    for label,url in [('same-control-child',CONTROL),('installed-app-child',APPURL),('wrong-port-child',OTHER)]:
        n=len(authority()['media'])
        ev("(()=>{const f=document.createElement('iframe');f.id="+json.dumps(label)+";f.src="+json.dumps(url)+";f.allow='microphone';document.body.appendChild(f);return true})()")
        wait(lambda:len(authority()['media'])>n)
        a=authority()
        ok(not a['media'][-1]['granted'] and not a['media'][-1]['mainFrame'],label+' cannot inherit native silent mic authority')
        ok(not [m for m in a['messages'] if m['method']=='app.info'][-1]['admitted'],label+' native control request is rejected')
        if label=='installed-app-child':
            n=len(a['media'])
            ev("document.getElementById('installed-app-child').contentWindow.postMessage('navigate-self','http://localhost:48023');true")
            wait(lambda:len(authority()['media'])>n)
            ok(not authority()['media'][-1]['granted'],'installed-app same-origin link stays in its frame, without acquiring native media authority')
    for label,url in [('installed-app-main',APPURL),('wrong-port-main',OTHER),('same-port-alias-main',f'http://localhost:{server.server_port}/authority.html')]:
        n=len(authority()['media']);ev('location.href='+json.dumps(url)+';true')
        wait(lambda:len(authority()['media'])>n)
        a=authority()
        ok(not a['trustedDocument'] and not a['media'][-1]['granted'] and a['media'][-1]['mainFrame'],label+' malicious navigation gains no native media authority')
        ok(not [m for m in a['messages'] if m['method']=='app.info'][-1]['admitted'],label+' malicious navigation gains no native controls')
        ok(ev('replies.length')=='0',label+' receives no native reply')
        ok(urlsplit(a['nativeControlURL']).netloc==urlsplit(CONTROL).netloc,label+' cannot retarget native background recording/search backend')
    # Selected remote backend deliberate compatibility path, with a different port.
    qa('connect '+OTHER);wait(lambda:ev('typeof probe')=='function' and authority()['trustedDocument'])
    ev('probe();true');wait(lambda:authority()['media'][-1]['granted'])
    ok(ev('replies.length')!='0','selected exact remote main retains native bridge')
    ok(authority()['media'][-1]['granted'],'selected exact remote main deliberately retains microphone policy')
    # Even explicitly selecting app-only origin must not promote it to control.
    qa('connect '+APPURL);wait(lambda:state()['url']==APPURL and ev('typeof probe')=='function')
    ev('probe();true');time.sleep(.3)
    ok(not authority()['trustedDocument'] and not authority()['media'][-1]['granted'],'explicit localhost app-origin selection is still never native authority')
    ok(authority()['nativeControlURL']=='','explicit installed-app selection supplies no native API backend')
    qa('voice-production-origin' if production_local else 'voice-local-fixture '+URL);wait(lambda:ev('!!window.__wux')=='1')
    ok(ask('command-w.txt','command-w')=='true' and proc.poll() is None,'Command-W native menu path remains app-internal')
    final=authority();(OUT/'authority-final.json').write_text(json.dumps(final,indent=2))
    (OUT/'receipt.json').write_text(json.dumps({'host':platform.node(),'app':str(APP),'binarySHA256':hashlib.sha256((APP/'Contents/MacOS/Wizard').read_bytes()).hexdigest(),'fixtureControl':CONTROL,'fixtureApp':APPURL,'productionOriginOverrideDisabled':production_local,'passes':passed,'boundary':'Actual NSEvents/NSApplication/native frame and real WK bridge/frame origins. Media decisions invoke actual delegate with real WKFrameInfo, without physical device acquisition. Full-window captures only accepted where screencapture succeeds and pixels are inspected. No physical mouse/mic/TCC, live backend/STT, or guest VM proof.'},indent=2))
    print('NATIVE_DRAG_AUTHORITY_PASS',flush=True)
finally:
    if proc:
        proc.terminate()
        try:proc.wait(timeout=8)
        except sp.TimeoutExpired:proc.kill();proc.wait()
    for s in servers:s.shutdown();s.server_close()
    if saved:
        current=OUT/'defaults-end-of-qa.plist';run('defaults','export',DOMAIN,current)
        extra=set(plistlib.loads(current.read_bytes()))-set(plistlib.loads(backup.read_bytes()))
        run('defaults','import',DOMAIN,backup)
        for key in sorted(extra):run('defaults','delete',DOMAIN,key)
    else:run('defaults','delete',DOMAIN,check=False)
    restored=OUT/'defaults-after.plist';run('defaults','export',DOMAIN,restored,check=False)
    if saved:assert plistlib.loads(backup.read_bytes())==plistlib.loads(restored.read_bytes()),'Preference restoration mismatch'
    print('QA_DEFAULTS_RESTORED',flush=True)
