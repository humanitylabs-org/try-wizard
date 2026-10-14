#!/usr/bin/env python3
"""Retire only the sampled probe-owned Host stuck before VM setup.
Never select/kill a foreign Host or a process with an initialized VM.
"""
import os,pathlib,signal,subprocess,time
R=pathlib.Path(os.environ['UPDATER_ROOT']); p=int(os.environ.get('UPDATER_RETIRE_PID','34180'))
sample=R/f'evidence/host-{p}.current.sample.txt'
r=subprocess.run(['ps','-p',str(p),'-o','args='],capture_output=True,text=True)
if not r.stdout.strip():raise SystemExit(0)
expected=str(R/'installed/Wizard.app/Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host')
assert r.stdout.strip() in (expected, expected+' --wizard-data-home '+str(R/'native-data')),'Refuse: PID is not this probe-owned Host'
subprocess.run(['/usr/bin/sample',str(p),'1','-file',str(sample)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
assert sample.is_file() and 'HostDelegate.applicationDidFinishLaunching' in sample.read_text() and 'mkdirat' in sample.read_text(),'Refuse: missing pre-VM initializer evidence'
os.kill(p,signal.SIGTERM);time.sleep(2)
if subprocess.run(['kill','-0',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:os.kill(p,signal.SIGKILL)
print('Retired only sampled probe-owned Host blocked in pre-VM mkdir; no guest or foreign Host force-stopped.')
