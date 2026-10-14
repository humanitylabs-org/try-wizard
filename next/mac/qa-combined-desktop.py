#!/usr/bin/env python3
"""Exact mounted Mac app + combined UX contracts, under caller-owned worker.lock.
Usage: <app> <UX web> <evidence>. Isolated local fixtures, no live sends/VM.
Native chords enter NSApplication; generated audio is not physical mic acceptance.
"""
import hashlib, http.server, json, platform, plistlib, subprocess as sp
import sys, threading, time
from pathlib import Path
from urllib.parse import unquote, urlsplit
APP, WEB, OUT = (Path(v).resolve() for v in sys.argv[1:4])
OUT.mkdir(parents=True, exist_ok=True)
DOMAIN = 'org.humanitylabs.wizard.mvp'
passed = []
class Fixture(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def translate_path(self, path):
        p = (WEB / unquote(urlsplit(path).path).removeprefix('/wizard-os-home/')).resolve()
        return str(p if p.is_relative_to(WEB) else WEB / '__denied__')
    def data(self, value):
        b = json.dumps(value).encode(); self.send_response(200)
        self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = urlsplit(self.path).path
        if p == '/api/voice/status': return self.data({'state':'ready','stage':'Local voice ready','downloaded':1,'total':1})
        if p.endswith('/bootstrap'): return self.data({'bootstrap':1,'settings':{'agent':{'name':'Wizard'}},'capabilities':{'voice':True},'endpoints':{}})
        if p.endswith('/model/options'): return self.data({'provider':'qa','model':'qa','providers':[]})
        if p.endswith('/api/sessions'):
            return self.data({'sessions':[{'id':'qa-command-a','title':'QA command A','status':'completed','updated_at':'2026-10-14T12:00:00Z'},{'id':'qa-command-b','title':'QA command B','status':'completed','updated_at':'2026-10-14T11:00:00Z'}],'has_more':False})
        if p.startswith('/wizard/') or p.startswith('/api/'):
            return self.data({'sessions':[],'messages':[],'apps':[],'items':[],'state':{}})
        return super().do_GET()
def run(*a, check=True):
    return sp.run(list(map(str,a)), check=check, text=True, stdout=sp.PIPE, stderr=sp.STDOUT, timeout=35)
def qa(cmd): run(OUT/'qa-post', cmd)
def ask(suffix, cmd):
    # Native diagnostic ABI has fixed /tmp replies; this runner creates no /tmp helpers.
    p = Path('/tmp/wizard-mvp-qa-'+suffix); p.unlink(missing_ok=True); qa(cmd)
    end = time.monotonic()+12
    while time.monotonic()<end:
        if p.exists(): return p.read_text()
        time.sleep(.1)
    raise AssertionError('Missing native callback: '+cmd)
def ev(code):
    x = ask('eval.txt', 'eval '+code); assert not x.startswith('ERROR'),x
    return x
def ok(c,n):
    assert c,n
    passed.append(n); print('PASS',n,flush=True)
def wait(code):
    end=time.monotonic()+15
    while time.monotonic()<end:
        if ev(code)=='1':return
        time.sleep(.2)
    raise AssertionError('Native state deadline: '+code)
def key(spec): qa('show-window'); qa('desktop-key '+spec); time.sleep(.5)
def composer(label):
    x=json.loads(ev("JSON.stringify((()=>{const e=document.querySelector('.win.focus .pane-main textarea'),f=e.closest('form'),b=e.closest('.wbody');const r=x=>{const q=x.getBoundingClientRect();return {x:q.x,y:q.y,bottom:q.bottom,height:q.height}};return {ta:r(e),form:r(f),box:r(b),logo:r(document.querySelector('#logo')),viewport:innerHeight,value:e.value}})())"))
    ok(x['ta']['height']>=38 and x['form']['bottom']<=x['box']['bottom']+1 and x['ta']['bottom']<=x['viewport'],label+' composer visible before typing')
    ok(x['logo']['x']>=86,label+' native traffic-light clearance')
    (OUT/(label+'-layout.json')).write_text(json.dumps(x,indent=2))
if platform.system()!='Darwin': raise SystemExit('Thales only')
if run('pgrep','-f',r'/Contents/MacOS/Wizard$',check=False).stdout.strip(): raise SystemExit('Another native app is running; preserve it')
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Fixture)
threading.Thread(target=server.serve_forever,daemon=True).start()
URL=f'http://127.0.0.1:{server.server_port}/wizard-os-home/desktop.html'
backup=OUT/'defaults-before.plist';saved=run('defaults','export',DOMAIN,backup,check=False).returncode==0
proc=None;receipt={'state':'running','passes':passed,'fixture':True,'app':str(APP),'url':URL}
try:
    notifier=OUT/'qa-post.swift'
    notifier.write_text('import Foundation\nDistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.mvp.qa"),object:CommandLine.arguments[1],userInfo:nil,deliverImmediately:true)\nRunLoop.main.run(until:Date().addingTimeInterval(0.1))\n')
    run('xcrun','swiftc','-O',notifier,'-o',OUT/'qa-post')
    for k in ['backends','activeBackend']:run('defaults','delete',DOMAIN,k,check=False)
    proc=sp.Popen([str(APP/'Contents/MacOS/Wizard'),'-QAHooks','YES','-QAWebStorage','YES','-DataHome',str(OUT/'data-home'),'-CapsLockRemap','NO','-SUEnableAutomaticChecks','NO'],stdout=(OUT/'app.log').open('w'),stderr=sp.STDOUT)
    time.sleep(2);qa('voice-local-fixture '+URL);wait('!!window.__wux && !!window.__wux.live.ok')
    # Keep the starting desktop nonempty: leaving an empty desktop now intentionally deletes it.
    ev("Object.values(__wux.wins).forEach(w=>__wux.closeWin(w.id));__wux.newChat();true")
    composer('initial')
    key('t');ok(ev('__wux.ws.length===2 && __wux.cur===1')=='1','native Command-T opens exactly one desktop')
    key('t,repeat');ok(ev('__wux.ws.length===2')=='1','native Command-T repeat does not duplicate')
    key('n');ok(ev("__wux.wins[__wux.ws[1].focus].thread==='__new__'")=='1','native Command-N opens current-desktop new chat')
    composer('new-chat')
    key('w');ok(ev('__wux.ws.length===2 && __wux.cur===1 && !__wux.ws[1].wins.length')=='1','first native Command-W closes only the app')
    key('w,repeat');ok(ev('__wux.ws.length===2')=='1','held native close does not remove empty desktop')
    key('w');ok(ev('__wux.ws.length===1 && __wux.cur===0')=='1','second native Command-W removes empty desktop')
    key('w');key('w');ok(proc.poll() is None and ev('__wux.ws.length===1')=='1','native root Command-W keeps Wizard open')
    key('n');key('t');key('n');key('[,shift');ok(ev('__wux.cur===0')=='1','native previous desktop chord')
    key('],shift');ok(ev('__wux.cur===1')=='1','native next desktop chord')
    ev("__wux.goWs(0);Object.values(__wux.wins).filter(w=>__wux.ws[0].wins.includes(w.id)).forEach(w=>__wux.closeWin(w.id));for(let i=0;i<3;i++)__wux.newWin({app:'chats'});window.__qaTiles=[...__wux.ws[0].wins];__wux.focusWin(__qaTiles[1]);true")
    for direction,index in [('down',2),('up',1),('left',0),('right',1)]:
        key(direction);ok(ev(f'__wux.ws[0].focus===__qaTiles[{index}]')=='1','native Command-'+direction+' selects adjacent app')
    key('f');ok(ev('__wux.ws[0].mono')=='1','native Command-F expands selected app')
    key('f');ok(ev('!__wux.ws[0].mono')=='1','native Command-F returns to tiles')
    ev("window.__qaRows=[...document.querySelectorAll('.win.focus .pane-list .ch-row[data-chopen]')].slice(0,2).map(r=>r.dataset.chopen);__wux.chats.openChat(__qaTiles[1],__qaRows[0]);true")
    ok(ev('__qaRows.length===2')=='1','fixture exposes two real rendered chat rows')
    key('down,option');ok(ev('__wux.wins[__qaTiles[1]].thread===__qaRows[1]')=='1','native Option-Down selects next chat')
    key('up,option');ok(ev('__wux.wins[__qaTiles[1]].thread===__qaRows[0]')=='1','native Option-Up selects previous chat')
    ev("__wux.newChat();const draft=document.querySelector('.win.focus .pane-main textarea');draft.value='combined QA draft';draft.dispatchEvent(new Event('input',{bubbles:true}));true")
    for size in ['700x1000','1120x1000','380x560']:
        qa('window-size '+size);time.sleep(.8);composer('size-'+size)
        ok(ev("document.querySelector('.win.focus .pane-main textarea').value==='combined QA draft'")=='1','resize '+size+' preserves draft')
    ev("__wux.goWs(1);__wux.goWs(0);true")
    ok(ev("document.querySelector('.win.focus .pane-main textarea').value==='combined QA draft'")=='1','desktop switch preserves draft')
    qa('snapshot '+str(OUT/'composer-webview.png'));time.sleep(.7)
    ev("window.__qaEnqueues=[];__wux.outbox.enqueue=async x=>{__qaEnqueues.push({kind:x.kind,sid:x.sessionId||'',bytes:x.audio?.size||0});return{id:'qa'};};navigator.mediaDevices.getUserMedia=async()=>{const ac=new AudioContext(),dest=ac.createMediaStreamDestination(),osc=ac.createOscillator();osc.connect(dest);osc.start();await ac.resume();window.__qaTone=ac;return dest.stream;};true")
    key('n,shift');wait("__wux.voice==='listen' && document.querySelector('#voiceText').textContent==='Listening · new chat'")
    ok(True,'native Command-Shift-N starts new-chat recording')
    time.sleep(1.3);key('n,shift');wait('__qaEnqueues.length===1');time.sleep(.6)
    captured=json.loads(ev('JSON.stringify(__qaEnqueues)'))
    ok(len(captured)==1 and captured[0]['kind']=='new' and not captured[0]['sid'] and captured[0]['bytes']>1200,'second native Command-Shift-N enqueues exactly one new-thread audio item')
    ok(proc.poll() is None and ev("__wux.voice==='idle'")=='1','new-voice completion keeps Wizard open')
    receipt['generatedAudio']=captured
    # A webview snapshot is explicitly not full AppKit chrome acceptance.
    receipt.update(state='passed',binarySHA256=hashlib.sha256((APP/'Contents/MacOS/Wizard').read_bytes()).hexdigest(),boundary='Actual AppKit event loop/menu to combined WK desktop, isolated HTTP fixtures and nonpersistent storage. Snapshot is WKWebView only. No physical keyboard/mouse/mic, live agent/STT or guest acceptance.')
    print('COMBINED_DESKTOP_PASS',flush=True)
except Exception as exc:
    receipt.update(state='failed',error=str(exc))
    try:(OUT/'failure-state.json').write_text(ev('JSON.stringify({cur:__wux.cur,desktops:__wux.ws,voice:__wux.voice,url:location.href})'))
    except Exception:pass
    raise
finally:
    if proc:
        proc.terminate()
        try:proc.wait(timeout=8)
        except sp.TimeoutExpired:proc.kill();proc.wait()
    server.shutdown();server.server_close()
    current=OUT/'defaults-end.plist';run('defaults','export',DOMAIN,current,check=False)
    if saved:
        extra=set(plistlib.loads(current.read_bytes()))-set(plistlib.loads(backup.read_bytes()))
        run('defaults','import',DOMAIN,backup)
        for k in sorted(extra):run('defaults','delete',DOMAIN,k)
    else:run('defaults','delete',DOMAIN,check=False)
    restored=OUT/'defaults-after.plist';run('defaults','export',DOMAIN,restored,check=False)
    if saved:assert plistlib.loads(backup.read_bytes())==plistlib.loads(restored.read_bytes()),'Preference restoration mismatch'
    receipt['defaultsRestored']=True;(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print('QA_DEFAULTS_RESTORED',flush=True)
