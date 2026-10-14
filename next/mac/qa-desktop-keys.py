#!/usr/bin/env python3
"""Thales native Wizard menu/event-loop acceptance. No real sends; defaults restored."""
import fcntl,json,pathlib,plistlib,subprocess as sp,time,os
BASE=pathlib.Path('/Volumes/ThalesMedia/Projects/wizard-desktop/dynamic-keys')
APP=BASE/'native/dist/Wizard.app';OUT=BASE/'evidence/native';OUT.mkdir(parents=True,exist_ok=True)
DOMAIN='org.humanitylabs.wizard';URL=os.environ.get('QA_NATIVE_URL','https://desktop-keys.staging.wizard001.com/wizard-os-home/desktop.html');passed=[]
def run(*args,check=True):return sp.run(args,check=check,text=True,stdout=sp.PIPE,stderr=sp.PIPE)
def qa(cmd):return run('/tmp/wizard-qa-post',cmd)
def ev(js):
 p=pathlib.Path('/tmp/wizard-qa-eval.txt');p.unlink(missing_ok=True);qa('eval '+js);end=time.monotonic()+12
 while time.monotonic()<end:
  if p.exists() and p.stat().st_size:
   x=p.read_text()
   if x.startswith('ERROR'):raise AssertionError(x)
   return x
  time.sleep(.1)
 raise AssertionError('eval deadline: '+js[:80])
def ok(c,n):
 if not c:raise AssertionError(n)
 passed.append(n);print('PASS',n,flush=True)
def key(spec):qa('show-window');qa('desktop-key '+spec);time.sleep(.4)
def wait(js):
 end=time.monotonic()+12
 while time.monotonic()<end:
  if ev(js)=='1':return
  time.sleep(.2)
 raise AssertionError('native state deadline: '+js)
lock=open('/Volumes/ThalesMedia/AndroidBuilds/worker.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
if run('pgrep','-f','/Wizard.app/Contents/MacOS/Wizard',check=False).stdout.strip():raise SystemExit('Prior native app is running; preserve it')
backup=OUT/'defaults.plist';saved=run('defaults','export',DOMAIN,str(backup),check=False).returncode==0;proc=None;receipt={}
try:
 for k,v in [('QAHooks','true'),('LegacyUX','false'),('voiceKeysEnabled','false')]:run('defaults','write',DOMAIN,k,'-bool',v)
 proc=sp.Popen([str(APP/'Contents/MacOS/Wizard')],stdout=(OUT/'app.log').open('w'),stderr=sp.STDOUT)
 time.sleep(2);qa('connect '+URL);end=time.monotonic()+50
 while time.monotonic()<end:
  try:
   if ev('!!window.__wux && !!window.__wux.live.ok')=='1':break
  except AssertionError:pass
  time.sleep(.4)
 else:raise AssertionError('native desktop did not load')
 ev("for(const d of __wux.ws)for(const id of [...d.wins])__wux.closeWin(id);__wux.goWs(0);while(__wux.ws.length>1){__wux.goWs(__wux.ws.length-1);__wux.closeDesktop();}true")
 key('t');ok(ev('__wux.ws.length===2 && __wux.cur===1')=='1','native Command-T menu opens exactly one desktop inside Wizard')
 key('t,repeat');ok(ev('__wux.ws.length===2')=='1','native autorepeat creates no duplicate desktop')
 key('n');ok(ev("__wux.wins[__wux.ws[1].focus].thread==='__new__'")=='1','native Command-N menu creates a chat inside the current desktop')
 key('w');ok(ev('__wux.ws.length===2 && __wux.cur===1 && !__wux.ws[1].wins.length')=='1','first native Command-W closes the app and leaves the desktop')
 key('w,repeat');ok(ev('__wux.ws.length===2')=='1','held native close never deletes the empty desktop')
 key('w');ok(ev('__wux.ws.length===1 && __wux.cur===0')=='1','second native Command-W removes empty desktop and returns to previous')
 key('w');ok(proc.poll() is None and ev('__wux.ws.length===1')=='1','native root Command-W keeps Wizard open')
 key('t');key('[,shift');ok(ev('__wux.cur===0')=='1','native previous-desktop menu works')
 key('],shift');ok(ev('__wux.cur===1')=='1','native next-desktop menu works')
 ev("__wux.goWs(0);for(let i=0;i<3;i++)__wux.newWin({app:'chats'});window.__nativeTiles=[...__wux.ws[0].wins];__wux.focusWin(__nativeTiles[1]);true")
 key('down');ok(ev('__wux.ws[0].focus===__nativeTiles[2]')=='1','native Command-Down selects the app below')
 key('up');ok(ev('__wux.ws[0].focus===__nativeTiles[1]')=='1','native Command-Up selects the app above')
 key('left');ok(ev('__wux.ws[0].focus===__nativeTiles[0]')=='1','native Command-Left selects the app to the left')
 key('right');ok(ev('__wux.ws[0].focus===__nativeTiles[1]')=='1','native Command-Right selects the app to the right')
 key('f');ok(ev('__wux.ws[0].mono')=='1','native Command-F expands the selected app')
 key('f');ok(ev('!__wux.ws[0].mono')=='1','native Command-F returns to tiling')
 ev("window.__nativeRows=[...document.querySelectorAll('.win.focus .pane-list .ch-row[data-chopen]')].slice(0,2).map(r=>r.dataset.chopen);__wux.chats.openChat(__nativeTiles[1],__nativeRows[0]);true");time.sleep(.3)
 key('down,option');ok(ev('__wux.wins[__nativeTiles[1]].thread===__nativeRows[1]')=='1','native Option-Down selects the next chat')
 key('up,option');ok(ev('__wux.wins[__nativeTiles[1]].thread===__nativeRows[0]')=='1','native Option-Up selects the previous chat')
 ev("window.__nativeEnqueues=[];__wux.outbox.enqueue=async x=>{__nativeEnqueues.push({kind:x.kind,sid:x.sessionId||'',bytes:x.audio?.size||0});return{id:'qa'};};navigator.mediaDevices.getUserMedia=async()=>{const ac=new AudioContext(),dest=ac.createMediaStreamDestination(),osc=ac.createOscillator();osc.connect(dest);osc.start();ac.resume();window.__qaTone=ac;return dest.stream;};true")
 key('n,shift');wait("__wux.voice==='listen' && document.querySelector('#voiceText').textContent==='Listening · new chat'");ok(True,'native new-voice menu starts a new-chat take while an existing chat is open')
 time.sleep(1.3);key('n,shift');wait('__nativeEnqueues.length===1');time.sleep(.5)
 data=json.loads(ev('JSON.stringify(__nativeEnqueues)'))
 ok(len(data)==1 and data[0]['kind']=='new' and data[0]['sid']=='' and data[0]['bytes']>1200,'second native new-voice chord enqueues exactly one new-thread audio message')
 ok(proc.poll() is None and ev("__wux.voice==='idle'")=='1','native Wizard remains open after sending voice')
 qa('snapshot '+str(OUT/'native-desktop-keys.png'));time.sleep(.7)
 receipt={'passed':passed,'app':str(APP),'version':'0.5.2','url':URL,'keyboard':'AppKit event loop with actual native menus, not DOM injection','audio':'generated test tone through actual MediaRecorder','captured':data}
except Exception:
 try:
  (OUT/'failure-state.json').write_text(ev("JSON.stringify({voice:__wux.voice,pill:document.querySelector('#voicePill').textContent,focus:__wux.ws[__wux.cur].focus,toast:document.querySelector('#toast').textContent})"))
  qa('snapshot '+str(OUT/'failure.png'));time.sleep(.5)
 except Exception:pass
 raise
finally:
 if proc:
  proc.terminate()
  try:proc.wait(timeout=8)
  except sp.TimeoutExpired:proc.kill();proc.wait()
 if saved:
  run('defaults','import',DOMAIN,str(backup));current=plistlib.loads(run('defaults','export',DOMAIN,'-').stdout.encode());assert current==plistlib.loads(backup.read_bytes()),'defaults restore mismatch';backup.unlink()
 else:run('defaults','delete',DOMAIN,check=False)
 lock.close()
if receipt:
 receipt['defaultsRestored']=True;(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2));print('NATIVE_DESKTOP_KEYS_PASS')
