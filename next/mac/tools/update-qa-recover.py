#!/usr/bin/env python3
"""Repair only this probe's identified failed preference cleanup, under worker.lock.
Unknown changes belong to someone else: refuse to roll them back.
"""
import json,os,pathlib,plistlib,signal,subprocess
R=pathlib.Path(os.environ['UPDATER_ROOT']); E=R/'evidence'; pref=E/'prefs-before.plist'; results=E/'native-results.json'
if not pref.exists() or not results.exists():raise SystemExit(0)
items=json.loads(results.read_text())
if not any(x['name']=='preexisting-preferences-restored' and not x['pass'] for x in items):raise SystemExit(0)
before=plistlib.loads(pref.read_bytes()); current=plistlib.loads(subprocess.check_output(['defaults','export','org.humanitylabs.wizard.mvp','-']))
changed={k for k in set(before)|set(current) if before.get(k)!=current.get(k)}
allowed={'SUUpdateGroupIdentifier','SULastCheckTime','QAWebStorage'}
assert changed<=allowed and current.get('DataHome')==before.get('DataHome'), 'Unknown preference changes; preserve other owner state and stop'
for row in subprocess.check_output(['ps','-axo','pid,args'],text=True).splitlines():
 parts=row.strip().split(None,1)
 if len(parts)==2 and parts[1].startswith(str(R/'installed/WizardOS.app/Contents/Frameworks/Sparkle.framework')+'/'):
  try:os.kill(int(parts[0]),signal.SIGTERM)
  except ProcessLookupError:pass
subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp'],check=True)
subprocess.run(['defaults','import','org.humanitylabs.wizard.mvp',str(pref)],check=True)
actual=plistlib.loads(subprocess.check_output(['defaults','export','org.humanitylabs.wizard.mvp','-']))
assert actual==before,'Exact preference repair readback failed'
(E/'preference-repair.json').write_text(json.dumps({'restored':True,'changed_keys':sorted(changed),'unknown_changes_overwritten':False})+'\n')
print('Restored exact prior preferences; only this probe-owned failed cleanup keys were changed.')
