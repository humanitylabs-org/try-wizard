#!/usr/bin/env python3
"""Run only on Thales under worker.lock. Real Sparkle install/relaunch, not a mock updater.
No VM/account preservation assertion is made by this native-only probe.
"""
import functools,http.server,json,os,pathlib,plistlib,shutil,signal,subprocess,threading,time,xml.etree.ElementTree as X
R=pathlib.Path(os.environ['UPDATER_ROOT']); S=R/'source/next/mac'; E=R/'evidence'; E.mkdir(exist_ok=True)
D=R/'native-data'; F=R/'feed'; A=R/'installed/Wizard.app'; NS='http://www.andymatuschak.org/xml-namespaces/sparkle'
receipts=[]; app=None; server=None; pref=E/'prefs-before.plist'; mode={'feed':'normal'}
def run(args,**kw):
 return subprocess.run([str(x) for x in args],check=True,**kw)
def out(args):return subprocess.check_output([str(x) for x in args],text=True).strip()
def wait(f,timeout=120):
 end=time.time()+timeout
 while time.time()<end:
  try:
   result=f()
   if result:return result
  except (OSError,ValueError,KeyError,RuntimeError):pass
  time.sleep(.3)
 raise RuntimeError('Timed out: '+str(f))
def state():
 q=D/'updates/qa.json'; q.unlink(missing_ok=True); run([E/'notify','update-state'],stdout=subprocess.DEVNULL)
 return wait(lambda:json.loads(q.read_text()),8)
def check(name,condition,detail=None):
 receipt={'name':name,'pass':bool(condition),'detail':detail}; receipts.append(receipt)
 (E/'native-results.json').write_text(json.dumps(receipts,indent=2)+'\n');print(json.dumps(receipt),flush=True)
 assert condition,name
def wait_state(predicate,timeout=120):
 def probe():
  s=state()
  return s if predicate(s) else None
 return wait(probe,timeout)
def qa(cmd):run([E/'notify',cmd],stdout=subprocess.DEVNULL)
def stop_native():
 try:
  s=state();qa('update-quit')
  if app:app.poll()
  wait(lambda:subprocess.run(['/bin/kill','-0',str(s['pid'])],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0,15)
 except (RuntimeError,OSError,KeyError):
  if app and app.poll() is None:app.terminate();app.wait(timeout=15)
def launch():
 global app
 app=subprocess.Popen([str(A/'Contents/MacOS/Wizard')],stdout=(E/'app-stdout.log').open('a'),stderr=(E/'app-stderr.log').open('a'))
 wait(lambda:state()['build'])
def stage(build):
 env={**os.environ,'VER':'0.6.'+str(build),'BUILD':str(build),'SPARKLE_DIR':str(R/'sparkle'),'SPARKLE_PUBLIC_KEY':public,'SPARKLE_FEED':'http://127.0.0.1:48210/appcast.xml','DMG':'0','RELEASE_ID':os.environ.get('RELEASE_ID','updater-native-local-qa')}
 with (E/f'build-{build}.log').open('w') as log:run(['/bin/bash',S/'build.sh'],env=env,stdout=log,stderr=subprocess.STDOUT)
 b=R/f'build-{build}/Wizard.app'; b.parent.mkdir(exist_ok=True); run(['/usr/bin/ditto',S/'dist/Wizard.app',b])
 run(['/usr/bin/python3',S/'tools/make-update-feed.py',b,F,'--base-url','http://127.0.0.1:48210','--sign-tool',R/'sparkle/bin/sign_update','--key-file',R/'signer/developer.key'])
 return b
class Handler(http.server.SimpleHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/appcast.xml' and mode['feed']=='offline':self.send_error(503);return
  super().do_GET()
 def log_message(self,format,*args):
  with (E/'feed-requests.log').open('a') as f:f.write(format%args+'\n')
try:
 run(['defaults','export','org.humanitylabs.wizard.mvp',pref]);os.chmod(pref,0o600)
 run(['xcrun','swiftc',S/'tools/update-qa-key.swift','-o',E/'keygen']); (R/'signer').mkdir(exist_ok=True,mode=0o700);os.chmod(R/'signer',0o700)
 public=out([E/'keygen',R/'signer/developer.key']); check('private-key-remains-restricted',((R/'signer/developer.key').stat().st_mode&0o777)==0o600)
 (E/'public-key.txt').write_text(public+'\n')
 run(['xcrun','swiftc',S/'tools/update-qa-notify.swift','-o',E/'notify'])
 run(['xcrun','swiftc',S/'Shared/Shared.swift',S/'Shared/UpdateContract.swift',S/'tools/update-contract-qa.swift','-o',E/'contract-qa'])
 bootstrap=stage(101); b102=stage(102)
 with (E/'contract-qa.log').open('w') as log:run([E/'contract-qa',bootstrap],stdout=log,stderr=subprocess.STDOUT)
 check('sealed-contract-tests',True)
 D.mkdir(exist_ok=True);run(['defaults','write','org.humanitylabs.wizard.mvp','DataHome',str(D)]);run(['defaults','write','org.humanitylabs.wizard.mvp','QAHooks','-bool','true'])
 # Clear only this temporary test connection setting; original preferences are privately backed up.
 subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp','backends'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 run(['defaults','write','org.humanitylabs.wizard.mvp','VoiceKeys','-bool','false'])
 run(['defaults','write','org.humanitylabs.wizard.mvp','QAWebStorage','-bool','true'])
 run(['/usr/bin/ditto',bootstrap,A]); server=http.server.ThreadingHTTPServer(('127.0.0.1',48210),functools.partial(Handler,directory=str(F)));threading.Thread(target=server.serve_forever,daemon=True).start()
 launch(); ready=wait_state(lambda s:s['phase']=='ready',180);check('automatic-check-and-authenticated-download',ready['ready'] and ready['build']=='101',ready)
 qa('snapshot '+str(E/'notice-101.png'));qa('update-later');time.sleep(.5);s=state();check('later-does-not-install',s['ready'] and not s['visible'] and s['build']=='101')
 qa('update-host-start');wait(lambda:state()['hostRunning'],30)
 hs=wait(lambda:json.loads((D/'host-status.json').read_text()),10);check('real-embedded-bootstrap-host-started',hs['build']=='101' and hs['dataHome']==str(D) and hs['state']=='notInstalled',hs)
 qa('update-check');qa('update-busy on');qa('update-restart');time.sleep(.5);s=state();check('busy-choice-defers-without-replacement',s['phase']=='busy' and s['build']=='101',s)
 qa('update-busy off');qa('update-restart');updated=wait_state(lambda s:s['build']=='102',180)
 check('actual-101-to-102-install-and-relaunch',updated['build']=='102',updated);check('custom-datahome-preserved',updated['dataHome']==str(D))
 wait_state(lambda s:s['phase']=='installed',30);hs=json.loads((D/'host-status.json').read_text());check('actual-Host-101-to-102-relaunch',hs['build']=='102' and hs['hostProtocol']==1 and hs['dataHome']==str(D),hs)
 run(['codesign','--verify','--deep','--strict',A]);check('installed-102-code-signature-valid',True)
 check('prior-101-bundle-retained',plistlib.loads((D/'updates/previous.app/Contents/Info.plist').read_bytes())['CFBundleVersion']=='101')
 stage(103);qa('update-check');wait(lambda:state()['phase']=='ready',180)
 qa('update-restart');updated=wait_state(lambda s:s['build']=='103',180);check('actual-102-to-103-install-and-relaunch',updated['build']=='103',updated)
 wait_state(lambda s:s['phase']=='installed',30);hs=json.loads((D/'host-status.json').read_text());check('actual-Host-102-to-103-relaunch',hs['build']=='103',hs)
 # Authenticated feed, corrupted archive: Sparkle must reject before installation.
 stage(104); damaged=F/'Wizard-104.zip'
 with damaged.open('r+b') as f:f.seek(100);one=f.read(1);f.seek(100);f.write(bytes([one[0]^1]))
 qa('update-check');failed=wait_state(lambda s:s['phase']=='failed',180);check('tampered-archive-rejected',failed['build']=='103',failed)
 # Invalid unsigned feed metadata must fail before any archive replacement.
 text=(F/'appcast.xml').read_text(); (F/'appcast.xml').write_text(text.replace('104','999'))
 qa('update-check');failed=wait_state(lambda s:s['phase']=='failed',60);check('tampered-feed-rejected',failed['build']=='103',failed)
 # Restore and sign a semantically incompatible, but authentic feed.
 (F/'appcast.xml').write_text(text)
 feed=F/'appcast.xml'; content=feed.read_text().replace('&quot;minimumPeer&quot;:1','&quot;minimumPeer&quot;:99').replace('"minimumPeer":1','"minimumPeer":99')
 feed.write_text(content);run([R/'sparkle/bin/sign_update','--ed-key-file',R/'signer/developer.key',feed]);qa('update-check');failed=wait_state(lambda s:s['phase']=='failed',60);check('authentic-incompatible-peer-rejected',failed['build']=='103',failed)
 mode['feed']='offline';qa('update-check');failed=wait_state(lambda s:s['phase']=='failed',60);check('offline-feed-leaves-usable-prior-bundle',failed['build']=='103',failed)
 qa('snapshot '+str(E/'failure-103.png'))
 # Actually launch the retained previously installed app, not just assert a file exists.
 stop_native(); prior=D/'updates/previous.app'; app=subprocess.Popen([str(prior/'Contents/MacOS/Wizard')],stdout=(E/'rollback-stdout.log').open('a'),stderr=(E/'rollback-stderr.log').open('a'))
 previous=wait_state(lambda s:s['build']=='102',30);check('retained-prior-bundle-is-usable',previous['dataHome']==str(D),previous)
 (E/'native-complete.json').write_text(json.dumps({'completed':True,'tests':len(receipts),'scope':'signed local feed + ad hoc Developer QA; no public feed, Apple notarization, real VM/chat/account preservation, or guest migration proof'},indent=2)+'\n')
finally:
 try:
  if (E/'notify').exists() and (D/'host-status.json').exists():
   hs=json.loads((D/'host-status.json').read_text());run([E/'notify','--host','quit'],stdout=subprocess.DEVNULL)
   wait(lambda:subprocess.run(['/bin/kill','-0',str(hs['pid'])],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0,15)
 finally:
  stop_native()
  if server:server.shutdown()
  # Only this probe's own staged Sparkle children, never another owner's bundle.
  for row in out(['ps','-axo','pid,args']).splitlines():
   fields=row.strip().split(None,1)
   if len(fields)==2 and fields[1].startswith(str(A/'Contents/Frameworks/Sparkle.framework/') ):
    try:os.kill(int(fields[0]),signal.SIGTERM)
    except ProcessLookupError:pass
  if pref.exists():
   subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   run(['defaults','import','org.humanitylabs.wizard.mvp',pref])
   wait(lambda:plistlib.loads(out(['defaults','export','org.humanitylabs.wizard.mvp','-']).encode())==plistlib.loads(pref.read_bytes()),10)
   check('preexisting-preferences-restored',True)
