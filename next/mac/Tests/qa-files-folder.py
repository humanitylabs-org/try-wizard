#!/usr/bin/env python3
"""Thales-only regression: real native onboarding and persisted folder choice."""
from pathlib import Path
import uuid
import subprocess as sp,json,time,os,plistlib
R=Path(__file__).resolve().parents[3]; MAC=R/'next/mac'; E=R/'evidence-files';E.mkdir(exist_ok=True)
DOMAIN='org.humanitylabs.wizard.mvp';DATA=E/('data-'+uuid.uuid4().hex);APP=MAC/'dist/Wizard.app'; POST=Path('/tmp/wizard-mvp-qa-post');STATE=Path('/tmp/wizard-mvp-qa-state.json')
def run(*args,check=True):return sp.run([str(a) for a in args],check=check,text=True,stdout=sp.PIPE,stderr=sp.STDOUT)
def qa(cmd):
 if POST.exists():run(POST,cmd)
 else:run('bash',MAC/'qa.sh',cmd)
def state():
 STATE.unlink(missing_ok=True);qa('state')
 for _ in range(100):
  if STATE.exists():return json.loads(STATE.read_text())
  time.sleep(.1)
 raise AssertionError('native QA state timeout')
ps=run('ps','-axo','pid=,command=').stdout
assert not any('Contents/MacOS/Wizard' in l and ('Wizard MVP.app/' in l or str(APP) in l) for l in ps.splitlines()),'Existing MVP app running; preserve it'
old=run('defaults','export',DOMAIN,'-',check=False);backup=old.stdout if old.returncode==0 else None
process=None
try:
 run('defaults','delete',DOMAIN,check=False)
 run('defaults','write',DOMAIN,'DataHome',str(DATA))
 run('defaults','write',DOMAIN,'QAHooks','-bool','true')
 run('defaults','write',DOMAIN,'osFeedURL','http://127.0.0.1:9/none.json')
 # Compile and run the real shared-folder implementation without creating the suggested user folder.
 run('xcrun','swiftc',MAC/'Shared/Shared.swift',MAC/'Tests/FilesFolderTests.swift','-o',E/'files-folder-tests')
 r=run(E/'files-folder-tests',E/('shared-state-test-'+uuid.uuid4().hex));print(r.stdout,flush=True)
 log=(E/'app.log').open('w');process=sp.Popen([str(APP/'Contents/MacOS/Wizard')],stdout=log,stderr=sp.STDOUT)
 time.sleep(3)
 records=[]
 for size,note in [('900x660',''),('640x460',''),('380x538',''),('380x538','WizardOS download: about 1.27 GB. Local voice models download once in the background. Keep at least 20 GB of free disk space available.')]:
  qa('window-size '+size);qa('files-folder-preview '+note);time.sleep(.6);s=state()
  assert s['title']=='Choose your shared folder' and not s['overlayHidden']
  assert s['subtitleLinesLimit']==0
  assert s['subtitleHeight']+.5>=s['subtitleRequiredHeight'],s
  assert 0<s['subtitleWidth']<=int(size.split('x')[0])-40,s
  assert 'Inbox' not in s['subtitle'] and 'Exports' not in s['subtitle']
  assert 'Documents, images, audio, videos and transcripts' in s['subtitle']
  assert 'Documents/Wizard MVP' in s['defaultFilesFolder'] and '/Application Support/' not in s['defaultFilesFolder']
  assert s['selectedFilesFolder']=='',s
  assert [b['title'] for b in s['overlayButtons']]==['Use This Folder','Choose Folder…','Back'],s
  assert all(b['visible'] and b['withinDocument'] and b['height']>20 and b['width']>=300 for b in s['overlayButtons']),s
  name=f'folder-{len(records)}-{size}.png';qa('snapshot '+str(E/name));time.sleep(.5)
  records.append({'size':size,'note':bool(note),'state':s,'screenshot':name})
 qa('click-overlay-button 2');time.sleep(.5)
 back=state();assert back['title']!='Choose your shared folder' and not back['overlayHidden']
 # Check unchanged legacy path remains authoritative on app relaunch without starting a VM.
 process.terminate();process.wait(timeout=20);process=None
 DATA.mkdir(exist_ok=True,parents=True);chosen=DATA/'Files';chosen.mkdir(exist_ok=True)
 (chosen/'user-file.txt').write_text('keep this document')
 (DATA/'files-folder.json').write_text(json.dumps({'path':str(chosen)}))
 process=sp.Popen([str(APP/'Contents/MacOS/Wizard')],stdout=log,stderr=sp.STDOUT);time.sleep(3)
 s=state();assert s['selectedFilesFolder']==str(chosen)
 assert (chosen/'user-file.txt').read_text()=='keep this document'
 (E/'receipt.json').write_text(json.dumps({'status':'passed','cases':records,'old_selection_preserved':True,'native_version':'0.6.1'},indent=2))
 print('FILES_ONBOARDING_NATIVE_LAYOUT_AND_PRESERVATION_PASS',flush=True)
finally:
 if process:
  process.terminate()
  try:process.wait(timeout=20)
  except sp.TimeoutExpired:process.kill();process.wait()
 if backup:
  f=E/'preferences-before.plist';f.write_text(backup);run('defaults','import',DOMAIN,f)
 else:run('defaults','delete',DOMAIN,check=False)
