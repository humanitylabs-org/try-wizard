#!/usr/bin/env python3
"""One no-VM native QA-control probe; no security settings or release changes."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import pwd
import signal
import subprocess as sp
import sys
import time

spec = importlib.util.spec_from_file_location('acceptance', Path(__file__).with_name('run.py'))
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s = m.read(sys.argv[1]); root = Path(s['probeRoot']); app = Path(s['probeApp'])
assert os.environ.get('WIZARD_HEAVY_JOB_ID'), 'durable worker required'
assert root.is_relative_to('/Volumes/ThalesMedia/') and not root.exists()
assert app.parent == Path('/Applications') and app.exists()
assert not m.mvp_processes()
assert m.sha(s['nativeNotifier']) == s['nativeNotifierSHA256']
root.mkdir(mode=0o700); data=root/'data'; data.mkdir(); (data/'Files').mkdir()
(data/'files-folder.json').write_text(json.dumps({'path':str(data/'Files')}))
def props():
    p=m.run(['defaults','export',m.DOMAIN,'-'],check=False)
    return plistlib.loads(p.stdout) if p.returncode==0 else None
before=props(); backup=root/'before.plist'; backup.write_bytes(plistlib.dumps(before or {})); backup.chmod(0o600)
config=dict(before or {}); config.update(DataHome=str(data),QAHooks=True,QAWebStorage=True,WizardKeyEnabled=False,VoiceKeysEnabled=False,backends=json.dumps([{'kind':'remote','name':'No-network QA-control probe','url':'http://127.0.0.1:49088/'}]).encode(),activeBackend=0,SUEnableAutomaticChecks=False)
prefs=root/'prefs.plist'; prefs.write_bytes(plistlib.dumps(config)); prefs.chmod(0o600)
r={'routes':[], 'candidateChanged':False, 'VMStarted':False}; child=None
uid=os.getuid(); gui=['sudo','-n','launchctl','asuser',str(uid),'sudo','-n','-u',pwd.getpwuid(uid).pw_name]
def acknowledge(argv,label):
    assert child is not None
    q = {}
    target=data/'updates/qa.json'
    if target.exists(): target.unlink()
    cmd=m.run(argv,check=False,timeout=10)
    end=time.monotonic()+4
    while time.monotonic()<end:
        q=m.read(target)
        if q.get('pid')==child.pid: break
        time.sleep(.2)
    r['routes'].append({'label':label,'returncode':cmd.returncode,'ack':q.get('pid')==child.pid,'build':q.get('build'),'stderr':cmd.stderr.decode(errors='replace')[-1500:]})
try:
    m.run(['defaults','import',m.DOMAIN,prefs]); assert props()==config
    with (root/'app.log').open('ab') as log:
        child=sp.Popen([str(app/'Contents/MacOS/Wizard')],stdout=log,stderr=sp.STDOUT)
    time.sleep(3)
    assert child.poll() is None
    code='ObjC.import("Foundation"); $.NSDistributedNotificationCenter.defaultCenter.postNotificationNameObjectUserInfoDeliverImmediately("org.humanitylabs.wizard.mvp.qa","update-state",null,true);'
    acknowledge(gui+['osascript','-l','JavaScript','-e',code], 'gui-JXA-no-drain')
    drained=code+' $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.25));'
    acknowledge(gui+['osascript','-l','JavaScript','-e',drained], 'gui-JXA-drained')
    acknowledge(gui+[s['nativeNotifier'],'update-state'],'gui-native-drained')
    acknowledge([s['nativeNotifier'],'update-state'],'inherited-native-drained')
    r['success']=any(x['ack'] for x in r['routes'])
    if not r['success']:
        m.run(['sample',str(child.pid),'2','-file',root/'app.sample.txt'],timeout=10,check=False)
finally:
    if child and child.poll() is None:
        child.terminate(); child.wait(timeout=15)
    if before is None: m.run(['defaults','delete',m.DOMAIN],check=False)
    else:
        for key in set(props() or {})-set(before): m.run(['defaults','delete',m.DOMAIN,key],check=False)
        m.run(['defaults','import',m.DOMAIN,backup])
    r['cleanupVerified']=props()==before and not m.owned_processes(app)
    (root/'result.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r))
assert r.get('success') and r['cleanupVerified']
