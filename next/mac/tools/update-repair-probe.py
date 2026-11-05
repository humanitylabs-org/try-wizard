#!/usr/bin/env python3
"""Thales-only under worker.lock: bounded real installer/Host diagnosis, not full QA."""
import functools,http.server,json,os,pathlib,plistlib,signal,subprocess,threading,time
R=pathlib.Path(os.environ['UPDATER_ROOT']); E=R/'evidence-repair'/os.environ.get('PROBE_ID','probe1'); E.mkdir(parents=True,exist_ok=False)
A=pathlib.Path(os.environ.get('UPDATER_INSTALL_PATH',str(R/'installed/WizardOS.app'))).expanduser()
# Normal Applications placement distinguishes updater code from a headless
# removable-volume permission gate. Only this explicitly owned QA bundle moves.
if 'UPDATER_INSTALL_PATH' in os.environ:
 assert A.parent==pathlib.Path.home()/'Applications' and A.name=='Wizard Updater QA.app'
A.parent.mkdir(parents=True,exist_ok=True)
D=pathlib.Path(os.environ.get('UPDATER_DATA_HOME',str(R/'native-data'))).expanduser()
if 'UPDATER_DATA_HOME' in os.environ:
 assert D == pathlib.Path.home()/'Library/Application Support/Wizard Updater QA'
D.mkdir(parents=True,exist_ok=True)
N=R/'evidence/notify'; pref=E/'prefs-before.plist'; server=None; app=None; host=None; receipts={}
def run(args,**kw): return subprocess.run([str(x) for x in args],check=True,timeout=kw.pop('timeout',15),**kw)
def output(args): return subprocess.check_output([str(x) for x in args],text=True,timeout=15).strip()
def save(name,data): (E/name).write_text(json.dumps(data,indent=2)+'\n'); print(name,json.dumps(data),flush=True)
def wait(fn,seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  try:
   x=fn()
   if x:return x
  except (OSError,ValueError,KeyError,subprocess.SubprocessError):pass
  time.sleep(.3)
 raise TimeoutError(str(fn))
def qa(cmd):run([N,cmd],stdout=subprocess.DEVNULL)
def state():
 p=D/'updates/qa.json'; p.unlink(missing_ok=True);qa('update-state')
 return wait(lambda:json.loads(p.read_text()),2)
def processes():
 result=[]
 for line in output(['ps','-axo','pid,ppid,args']).splitlines():
  f=line.strip().split(None,2)
  if len(f)==3 and f[2].startswith(str(A/'Contents/')): result.append({'pid':int(f[0]),'ppid':int(f[1]),'command':f[2]})
 return result
def samples(label):
 rows=processes(); save(label+'-processes.json',rows)
 for row in rows:
  if row['pid']==os.getpid():continue
  p=E/(label+'-'+str(row['pid'])+'.sample.txt')
  subprocess.run(['/usr/bin/sample',str(row['pid']),'1','1','-file',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
  if p.exists(): print('SAMPLE',p,'\n',p.read_text().split('Binary Images:')[0][-13000:],flush=True)
def logs():
 # Read-only daemon stack links a filesystem wait to macOS privacy IPC.
 daemon=output(['pgrep','-x','sandboxd'])
 if daemon.isdecimal():
  subprocess.run(['sudo','-n','/usr/bin/sample',daemon,'1','1','-file',str(E/'sandboxd.sample.txt')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
 predicate='(process == "Autoupdate") OR (process == "Updater") OR (process == "sandboxd") OR (process == "tccd") OR (subsystem CONTAINS "sparkle")'
 p=E/'unified.log'
 with p.open('w') as f: subprocess.run(['/usr/bin/log','show','--last','5m','--style','compact','--info','--debug','--predicate',predicate],stdout=f,stderr=subprocess.STDOUT,timeout=30)
 print('LOG',p,flush=True)
try:
 save('lock.json',{'acquiredUTC':output(['date','-u','+%FT%TZ']),'pid':os.getpid()})
 import hashlib,xml.etree.ElementTree as X
 feed=R/'feed/appcast.xml'; archive=R/'feed/Wizard-102.zip'
 enclosure=X.parse(feed).find('.//enclosure'); assert enclosure is not None
 sig=enclosure.attrib['{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature']
 sign=[R/'sparkle/bin/sign_update','--ed-key-file',R/'signer/developer.key','--verify']
 run([*sign,feed]);run([*sign,archive,sig])
 save('signatures.json',{'archiveSHA256':hashlib.sha256(archive.read_bytes()).hexdigest(),'feedSHA256':hashlib.sha256(feed.read_bytes()).hexdigest(),'officialArchiveAndFeedVerification':True})
 run(['defaults','export','org.humanitylabs.wizard.mvp',pref]);os.chmod(pref,0o600)
 for key,val in [('DataHome',str(D))]:run(['defaults','write','org.humanitylabs.wizard.mvp',key,val])
 for key,val in [('QAHooks','true'),('VoiceKeys','false'),('QAWebStorage','true')]:run(['defaults','write','org.humanitylabs.wizard.mvp',key,'-bool',val])
 subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp','backends'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 assert not processes(),'owned candidate already active'
 run(['/usr/bin/ditto',R/'build-101/WizardOS.app',A])
 for name in ['host-status.json','updates/transaction.json','updates/ui.json']:(D/name).unlink(missing_ok=True)
 h=A/'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host'
 host=subprocess.Popen([str(h),'--wizard-data-home',str(D)],stdout=(E/'host.stdout').open('w'),stderr=(E/'host.stderr').open('w'))
 try:
  hs=wait(lambda:json.loads((D/'host-status.json').read_text()),8);save('host-start.json',hs)
  run([N,'--host','quit']);host.wait(timeout=10);receipts['hostInitializerPassed']=True
 except (TimeoutError,subprocess.TimeoutExpired):
  receipts['hostInitializerPassed']=False;samples('host-stall')
  # Only an owned pre-VM process with the current initializer stall may be retired.
  p=E/('host-stall-'+str(host.pid)+'.sample.txt');text=p.read_text() if p.exists() else ''
  assert 'applicationDidFinishLaunching' in text and 'mkdirat' in text and not (D/'host-status.json').exists(),'unproven pre-VM stall: leave process untouched'
  host.terminate();host.wait(timeout=10)
 server=http.server.ThreadingHTTPServer(('127.0.0.1',48210),functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(R/'feed')));threading.Thread(target=server.serve_forever,daemon=True).start()
 app=subprocess.Popen([str(A/'Contents/MacOS/Wizard')],stdout=(E/'app.stdout').open('w'),stderr=(E/'app.stderr').open('w'))
 ready=wait(lambda:(lambda s:s if s['phase']=='ready' else None)(state()),25);save('ready.json',ready)
 qa('update-restart')
 try:
  s=wait(lambda:(lambda s:s if s['build']=='102' else None)(state()),25);save('relaunch.json',s);receipts['nativeInstallRelaunch']=True
 except TimeoutError:
  receipts['nativeInstallRelaunch']=False;samples('install-stall')
  for n in ['ui.json','transaction.json']:
   p=D/'updates'/n
   if p.exists():save(n,json.loads(p.read_text()))
 receipts['installedBuild']=plistlib.loads((A/'Contents/Info.plist').read_bytes())['CFBundleVersion']
 if receipts.get('nativeInstallRelaunch'):
  run(['/usr/bin/codesign','--verify','--deep','--strict',A]); receipts['installedCodeSignatureValid']=True
  rows=processes();save('relaunch-processes.json',rows)
  assert any(row['command']==str(A/'Contents/MacOS/Wizard') for row in rows),'new app has no live PID'
 logs();save('result.json',receipts)
finally:
 if app:
  try:qa('update-quit');app.wait(timeout=10)
  except subprocess.SubprocessError:pass
 # Do not force kill apps. Only own Sparkle auxiliary tools receive TERM on diagnostic cleanup.
 for row in processes():
  if row['command'].startswith(str(A/'Contents/Frameworks/Sparkle.framework/')):
   try:os.kill(row['pid'],signal.SIGTERM)
   except ProcessLookupError:pass
 if server:server.shutdown()
 if pref.exists():
  subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  run(['defaults','import','org.humanitylabs.wizard.mvp',pref])
  actual=plistlib.loads(output(['defaults','export','org.humanitylabs.wizard.mvp','-']).encode());assert actual==plistlib.loads(pref.read_bytes())
  save('cleanup.json',{'prefsExactlyRestored':True,'ownedProcessesRemaining':processes()})
