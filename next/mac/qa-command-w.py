#!/usr/bin/env python3
"""Thales native regression: exercise Command-W through AppKit's real menu.
Usage: python3 qa-command-w.py dist/WizardOS.app https://.../wizard-os-home/desktop.html
Run under the shared worker lock. Keeps defaults and any prior Wizard.app intact.
"""
import json, os, pathlib, subprocess as sp, sys, time
APP=pathlib.Path(sys.argv[1]).resolve(); URL=sys.argv[2]
OUT=pathlib.Path(os.environ.get('QA_OUT','command-w-native-evidence')).resolve(); OUT.mkdir(parents=True,exist_ok=True)
HOME=pathlib.Path.home(); domain='org.humanitylabs.wizard.mvp'; passed=[]
qa_driver_ready=False
def run(*args,check=True):
 global qa_driver_ready
 is_qa=args[:2]==('bash','qa.sh')
 # qa.sh rebuilds its tiny Swift notifier on every call. Bootstrap once so the QA harness
 # itself does not consume the two-second real-user confirmation interval.
 if is_qa and qa_driver_ready: args=('/tmp/wizard-mvp-qa-post',args[2])
 result=sp.run(args,check=check,text=True,stdout=sp.PIPE,stderr=sp.PIPE)
 if is_qa and result.returncode==0: qa_driver_ready=True
 return result
def waitfile(file,cmd):
 p=pathlib.Path(file);p.unlink(missing_ok=True);run('bash','qa.sh',cmd)
 end=time.monotonic()+12
 while time.monotonic()<end:
  if p.exists() and p.stat().st_size: return p.read_text()
  time.sleep(.15)
 raise AssertionError(f'QA command timed out: {cmd}')
def ev(js):
 text=waitfile('/tmp/wizard-mvp-qa-eval.txt','eval '+js)
 if text.startswith('ERROR'): raise AssertionError(text)
 return text
def state(): return json.loads(waitfile('/tmp/wizard-mvp-qa-keys.json','keys-state'))
def ok(c,n):
 if not c: raise AssertionError(n)
 passed.append(n);print('PASS',n,flush=True)
def command():
 run('bash','qa.sh','show-window')
 result=waitfile('/tmp/wizard-mvp-qa-command-w.txt','command-w');ok(result=='true','AppKit accepts the Command-W menu equivalent');time.sleep(.3)
prior=run('pgrep','-f',r'/(Wizard|WizardOS|Wizard MVP)\.app/Contents/MacOS/Wizard',check=False).stdout.splitlines()
if prior: raise SystemExit('Another WizardOS or legacy Wizard app is running; leave it intact and queue QA.')
backup=OUT/'defaults.plist'; saved=run('defaults','export',domain,str(backup),check=False).returncode==0
proc=None
try:
 run('defaults','write',domain,'QAHooks','-bool','true')
 run('defaults','write',domain,'LegacyUX','-bool','false')
 run('defaults','write',domain,'voiceKeysEnabled','-bool','false')
 proc=sp.Popen([str(APP/'Contents/MacOS/Wizard')],stdout=(OUT/'app.log').open('w'),stderr=sp.STDOUT)
 time.sleep(2)
 run('bash','qa.sh','connect '+URL)
 end=time.monotonic()+50
 while time.monotonic()<end:
  try:
   if ev('!!window.__wux && !!window.__wux.live.ok')=='1': break
  except AssertionError: pass
  time.sleep(.5)
 else: raise AssertionError('Native desktop did not load')
 ok(state()['windowVisible'],'native main window is visible')
 # This QA origin has its own fresh web storage; live James state is never opened.
 ev("__wux.goWs(0);for(const id of [...__wux.ws[0].wins])__wux.closeWin(id);true")
 command();ok(ev('__wux.ws[0].wins.length')=='0' and state()['windowVisible'],'Command-W on empty desktop preserves native window')
 ev("__wux.newWin({app:'chats',thread:'__new__'});true")
 command();ok(ev('__wux.ws[0].wins.length')=='0' and state()['windowVisible'],'last New chat closes inside native app without hiding Wizard')
 ev("__wux.newWin({app:'chats'});__wux.newWin({app:'chats',thread:'__new__'});true")
 command();ok(ev('__wux.ws[0].wins.length')=='1' and state()['windowVisible'],'native Command-W closes exactly one of two apps')
 command();command();ok(ev('__wux.ws[0].wins.length')=='0' and state()['windowVisible'],'repeated native Command-W remains at desktop root')
 ok(proc.poll() is None and state()['activationPolicy']==0,'Wizard remains running as a regular foreground app')
 run('bash','qa.sh','snapshot '+str(OUT/'desktop-root.png'));time.sleep(1)
 # Quit guard: real AppKit menu action on first/second presses, with expiry and repeat checks.
 ok(waitfile('/tmp/wizard-mvp-qa-command-q.txt','command-q')=='true','AppKit accepts Command-Q through the guarded action')
 st=state();ok(proc.poll() is None and st['windowVisible'] and st['quitHintVisible'] and st['quitArmed'],'first Command-Q shows press-again prompt and keeps Wizard running')
 run('bash','qa.sh','panel-snapshot quit '+str(OUT/'quit-confirmation.png'))
 run('bash','qa.sh','command-q-repeat');time.sleep(.2)
 ok(proc.poll() is None and state()['quitArmed'],'held-key repeat never confirms quit')
 time.sleep(2.1);st=state();ok(not st['quitArmed'] and not st['quitHintVisible'] and proc.poll() is None,'confirmation expires and prompt hides after two seconds')
 ok(waitfile('/tmp/wizard-mvp-qa-command-q.txt','command-q')=='true' and state()['quitArmed'],'Command-Q after expiry starts a fresh confirmation')
 # Second distinct press goes through the actual menu and terminates the native process.
 before=state();run('bash','qa.sh','command-q');proc.wait(timeout=6)
 ok(proc.returncode==0,'second Command-Q inside the confirmation interval exits Wizard cleanly')
 receipt={'passed':passed,'app':str(APP),'version':run('defaults','read',str(APP/'Contents/Info.plist'),'CFBundleShortVersionString').stdout.strip(),'url':URL,'state':before,'confirmedQuitExitCode':proc.returncode}
 (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2));print('NATIVE_COMMAND_W_PASS',flush=True)
finally:
 if proc:
  proc.terminate()
  try:proc.wait(timeout=8)
  except sp.TimeoutExpired:proc.kill();proc.wait()
 if saved:run('defaults','import',domain,str(backup))
 else:run('defaults','delete',domain,check=False)
