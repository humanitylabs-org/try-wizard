#!/usr/bin/env python3
"""Thales-only native regression, under the shared worker lock.
Usage: python3 qa-native-voice-shortcut.py <DMG-extracted app> <packaged UX web> <evidence dir>
Exercises NSApplication.sendEvent -> installed NSEvent local monitor -> native
wizard:orb bridge -> unchanged desktop voice/MediaRecorder/outbox. Protocol
responses and oscillator microphone are explicit fixtures, NOT physical mic/STT
or guest-VM acceptance. Never contacts a real agent or opens an existing VM.
"""
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import subprocess as sp
import sys
import threading
import time
from urllib.parse import urlsplit, unquote

APP, WEB, OUT = (Path(v).resolve() for v in sys.argv[1:4])
OUT.mkdir(parents=True, exist_ok=True)
HERE = Path(__file__).resolve().parent
DOMAIN = 'org.humanitylabs.wizard.mvp'
passed, writes, reads = [], [], []
status = {'state': 'ready', 'stage': 'Local voice ready', 'downloaded': 1234567, 'total': 1234567}
http_status = 200
retry_count = 0

class Fixture(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def translate_path(self, path):
        relative = unquote(urlsplit(path).path).removeprefix('/wizard-os-home/')
        p = (WEB / relative).resolve()
        return str(p if p.is_relative_to(WEB) else WEB / '__not_allowed__')
    def response(self, value, code=200):
        data = json.dumps(value).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        p = urlsplit(self.path).path
        reads.append(p)
        if p == '/api/voice/status': return self.response(status, http_status)
        if p == '/wizard/hermes/api/model/options':
            return self.response({'provider':'qa-fixture', 'model':'qa-model', 'providers':[{'slug':'qa-fixture','name':'QA only','authenticated':True,'is_current':True,'models':['qa-model']}]})
        if p == '/wizard/hermes/api/sessions': return self.response({'sessions':[], 'has_more':False})
        if p.startswith('/wizard/') or p.startswith('/api/') or '/api/' in p:
            if p.endswith('/bootstrap'): return self.response({'bootstrap':1, 'settings':{'agent':{'name':'Wizard'}}, 'capabilities':{'voice':True,'files':True}, 'endpoints':{'transcribe':'/wizard/voice/transcribe', 'upload':'/wizard/files/upload'}})
            return self.response({'state':{}, 'messages':[], 'apps':[], 'items':[]})
        return super().do_GET()
    def do_POST(self):
        global retry_count
        p = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        writes.append({'path':p, 'bytes':len(body), 'contentType':self.headers.get('Content-Type','')})
        if self.headers.get('Content-Type','').startswith('application/json'):
            writes[-1]['payload'] = json.loads(body or b'{}')
        if p == '/api/voice/retry': retry_count += 1; return self.response({'accepted':True}, 202)
        if p.endswith('/transcribe'): return self.response({'text':'qa generated audio', 'ms':1})
        if p.endswith('/files/upload'): return self.response({'file':{'id':'drop_qa_native','filename':'voice.mp4','mime':'audio/mp4','bytes':len(body)}}, 201)
        if p.endswith('/api/sessions'): return self.response({'session':{'id':'qa-native-voice'}})
        if p.endswith('/v1/runs'): return self.response({'run_id':'qa-native-run','status':'queued'}, 202)
        return self.response({})
    def do_PUT(self): self.do_POST()

server = http.server.ThreadingHTTPServer(('127.0.0.1',0), Fixture)
thread = threading.Thread(target=server.serve_forever, daemon=True)
URL = f'http://127.0.0.1:{server.server_port}/wizard-os-home/desktop.html'

def run(*args, check=True):
    return sp.run(list(map(str,args)), check=check, text=True, stdout=sp.PIPE, stderr=sp.STDOUT, timeout=30)

def qa(cmd):
    run(OUT / 'qa-post', cmd)

def ask(suffix, cmd):
    p = Path('/tmp/wizard-mvp-qa-' + suffix); p.unlink(missing_ok=True); qa(cmd)
    until = time.monotonic()+12
    while time.monotonic()<until:
        if p.exists(): return p.read_text()
        time.sleep(.1)
    raise AssertionError('No native QA reply: '+cmd)

def state(): return json.loads(ask('state.json','state'))
def voice(): return json.loads(ask('meeting.json','meeting-state'))['voice']
def ev(code):
    result = ask('eval.txt','eval '+code)
    if result.startswith('ERROR'): raise AssertionError(result)
    return result

def wait(fn, seconds=35):
    until=time.monotonic()+seconds; last=None
    while time.monotonic()<until:
        last=fn()
        if last: return last
        time.sleep(.25)
    raise AssertionError('Timed out: '+str(last))

def ok(condition, name):
    assert condition, name
    passed.append(name); print('PASS',name,flush=True)

def tap(code=54, flags=1048576, duration=.12, chord=False):
    spec = f'flags {code} {flags} 0;'
    if chord: spec += f'key 8 {flags} 0.05;'
    spec += f'flags {code} 0 {duration}'
    qa('voice-native-event '+spec)

def snapshot(name):
    qa('snapshot '+str(OUT / (name+'.png')))
    wait(lambda:(OUT / (name+'.png')).exists())

def runs(): return [w for w in writes if w['path'].endswith('/v1/runs') or w['path'].endswith('/api/sessions')]

if platform.system()!='Darwin': raise SystemExit('Must execute on Thales/macOS')
prior = run('pgrep','-f',r'/Contents/MacOS/Wizard$',check=False).stdout.strip()
if prior: raise SystemExit('Another native Wizard is running; queue QA, do not kill it: '+prior)
backup=OUT/'defaults-before.plist'
saved=run('defaults','export',DOMAIN,backup,check=False).returncode==0
proc=None
try:
    # Compile a private notifier once; no shared QA driver recompilation races.
    notifier=OUT/'qa-post.swift'
    notifier.write_text('import Foundation\nDistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.mvp.qa"), object: CommandLine.arguments[1], userInfo: nil, deliverImmediately: true)\nRunLoop.main.run(until: Date().addingTimeInterval(0.1))\n')
    run('xcrun','swiftc','-O',notifier,'-o',OUT/'qa-post')
    run('defaults','delete',DOMAIN,check=False)
    thread.start()
    proc=sp.Popen([str(APP/'Contents/MacOS/Wizard'),'-QAHooks','YES','-QAWebStorage','YES','-DataHome',str(OUT/'data-home'),'-CapsLockRemap','NO'],stdout=(OUT/'native-app.log').open('w'),stderr=sp.STDOUT)
    time.sleep(2)
    qa('voice-local-fixture '+URL)
    wait(lambda: ev('!!window.__wux && !!window.__wux.live.ok')=='1')
    wait(lambda:state()['overlayHidden'] and not state()['localVoice']['visible'])
    v=voice()
    ok(v['enabled'] and v['monitors']==1,'first-launch preference enables the real local NSEvent monitor')
    (OUT/'initial-native-state.json').write_text(json.dumps({'voice':v,'state':state()},indent=2))
    ok(not v['trusted'],'foreground event path exercised WITHOUT Accessibility permission')
    ok(not v['globalMonitor'],'foreground default does not install a system-wide keyboard monitor')
    local=state()['localVoice']
    ok(local['height']==0 and local['summary']=='' and local['polling'],'ready removes footer/counters/retry while monitoring continues')
    ok(abs(local['webHeight']-local['contentHeight'])<1,'ready returns full native content height to WKWebView')
    snapshot('ready-no-footer')
    for phase in ['preparing','error','retrying']:
        status.update(state=phase,stage='QA '+phase)
        wait(lambda:state()['localVoice']['visible'] and phase in state()['localVoice']['summary'].lower())
        s=state()['localVoice']
        ok(s['height']==64 and s['retryEnabled'],phase+' preserves visible recovery')
        if phase=='error': snapshot('error-recovery')
    qa('voice-retry');wait(lambda:retry_count==1)
    ok(retry_count==1,'native Retry button action reaches protocol POST once')
    status.update(state='ready',stage='Local voice ready')
    wait(lambda:not state()['localVoice']['visible'])
    ok(state()['localVoice']['summary']=='','recovery collapses footer again without reload')
    http_status=503
    wait(lambda:'unavailable' in state()['localVoice']['summary'])
    ok(state()['localVoice']['visible'] and state()['localVoice']['retryEnabled'],'unavailable status re-exposes readable recovery after ready')
    http_status=200
    wait(lambda:not state()['localVoice']['visible'])
    qa('connect '+URL);wait(lambda:not state()['localVoice']['polling'])
    ok(not state()['localVoice']['visible'],'remote backend clears local status/polling')
    qa('voice-local-fixture '+URL)
    wait(lambda:ev('!!window.__wux && !!window.__wux.live.ok')=='1')
    wait(lambda:not state()['localVoice']['visible'] and state()['localVoice']['polling'])
    # Use real AudioContext/MediaRecorder, but a generated oscillator stream.
    # No physical microphone, TCC grant, transcription provider or real agent.
    ev("(() => { window.qaErrors=[];addEventListener('error',e=>qaErrors.push(String(e.message)));window.qaOrb=[];addEventListener('wizard:orb-state',e=>qaOrb.push(e.detail.state)); const AC=window.AudioContext||window.webkitAudioContext;window.qaAC=new AC();const dst=qaAC.createMediaStreamDestination();const osc=qaAC.createOscillator();osc.frequency.value=220;osc.connect(dst);osc.start();qaAC.resume();Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>dst.stream.clone(),configurable:true});localStorage.setItem('wos.coached','true'); __wux.goWs(0);for(const id of [...__wux.ws[0].wins])__wux.closeWin(id);__wux.newWin({app:'chats',thread:'__new__'});return true})()")
    wait(lambda:ev("!!document.querySelector('.win.focus textarea')")=='1')
    ev("const ta=document.querySelector('.win.focus textarea');ta.value='unsent native draft';ta.dispatchEvent(new Event('input',{bubbles:true}));true")
    initial=len(runs()); count=voice()['orbTaps']
    tap();wait(lambda:ev('__wux.voice')=='listen')
    ok(voice()['orbTaps']==count+1 and ev('qaOrb.at(-1)')=='voice','Right Command NSEvents start exactly one established voice capture')
    ok(len(runs())==initial and ev("document.querySelector('.win.focus textarea').value")=='unsent native draft','first voice tap neither sends nor loses typed draft')
    snapshot('native-command-listening')
    time.sleep(1.3)
    tap();wait(lambda:ev('__wux.voice')=='idle')
    wait(lambda:any(w['path'].endswith('/v1/runs') for w in writes))
    ok(voice()['orbTaps']==count+2 and ev('qaOrb.at(-1)')=='sent','second Right Command NSEvents finish once through existing voice/outbox path')
    ok(any(w['path'].endswith('/transcribe') and w['bytes']>1200 for w in writes),'actual generated MediaRecorder audio reaches fixture transcription')
    admitted=[w['payload'] for w in writes if w['path'].endswith('/v1/runs')]
    ok(len(admitted)==1 and admitted[0]['input']=='unsent native draft\n\nqa generated audio','deliberate second tap sends typed draft with transcript exactly once (existing contract)')
    count=voice()['orbTaps']; sent=len(runs())
    tap(chord=True);tap(duration=.6);tap(code=55);tap(code=61,flags=524288)
    ok(voice()['orbTaps']==count and voice()['mode']=='idle' and ev('__wux.voice')=='idle' and len(runs())==sent,'Command-C chord, held/Left Command and default Right Option never trigger voice/send')
    qa('voice-enable off');tap()
    ok(not voice()['enabled'] and voice()['orbTaps']==count,'explicit disabled preference is respected')
    qa('voice-default')
    ok(voice()['enabled'] and voice()['monitors']==1,'restoring default reinstalls one local monitor, not duplicates')
    # Fresh stream per recording, including the manual visible microphone.
    ev("document.querySelector('#micBtn').click();true")
    wait(lambda:ev('__wux.voice')=='listen')
    ok(voice()['orbTaps']==count,'manual visible microphone still starts the same capture independently')
    ev("dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true}));true")
    wait(lambda:ev('__wux.voice')=='idle')
    ok(len(runs())==sent,'Escape cancels manual recording without sending')
    for size in ['700x780','1120x1000']:
        qa('window-size '+size);s=state()['localVoice']
        ok(s['height']==0 and abs(s['webHeight']-s['contentHeight'])<1,'no ready footer gap at '+size)
    ok(ask('command-w.txt','command-w')=='true','existing Command-W still routes through native menu')
    ok(proc.poll() is None and json.loads(ask('keys.json','keys-state'))['windowVisible'],'native window remains open after internal Command-W')
    ok(ev('JSON.stringify(qaErrors)')=='[]','no uncaught errors on exercised desktop voice path')
    receipt={'host':platform.node(),'platform':platform.platform(),'app':str(APP),'binarySHA256':hashlib.sha256((APP/'Contents/MacOS/Wizard').read_bytes()).hexdigest(),'packagedUX':str(WEB),'passes':passed,'initialVoice':v,'requests':writes,'voiceStatusGETs':reads.count('/api/voice/status'),'boundary':'Generated oscillator microphone and protocol fixtures; actual AppKit event monitor, WKWebView bridge, unchanged packaged UX, MediaRecorder and outbox. No physical keyboard/mic, live STT or guest VM acceptance.'}
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print('NATIVE_VOICE_SHORTCUT_PASS',flush=True)
finally:
    if proc:
        proc.terminate()
        try:proc.wait(timeout=8)
        except sp.TimeoutExpired:proc.kill();proc.wait()
    server.shutdown();server.server_close()
    run('defaults','delete',DOMAIN,check=False)
    if saved:run('defaults','import',DOMAIN,backup)
    restored=OUT/'defaults-after.plist'
    result=run('defaults','export',DOMAIN,restored,check=False)
    if saved:
        import plistlib
        assert plistlib.loads(backup.read_bytes())==plistlib.loads(restored.read_bytes()),'QA preferences were not restored'
        print('QA_DEFAULTS_RESTORED',flush=True)
    else: print('QA_DEFAULTS_ABSENT_RESTORED',flush=True)
