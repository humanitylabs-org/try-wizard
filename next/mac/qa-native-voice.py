#!/usr/bin/env python3
"""Thales-only: actual native status, retry and local/remote switch on an isolated QA VM."""
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error

HERE=Path(__file__).resolve().parent

def command(cmd):
    subprocess.run(['bash',str(HERE/'qa.sh'),cmd],check=True,timeout=10)

def state():
    command('state'); time.sleep(.3)
    return json.loads(Path('/tmp/wizard-mvp-qa-state.json').read_text())

def guest(cmd):
    return subprocess.check_output(['bash',str(HERE/'qa-guest.sh'),cmd],text=True,timeout=60)

def wait(check,seconds=60):
    s={}
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        s=state()
        if check(s): return s
        time.sleep(1)
    raise AssertionError(s)

s=wait(lambda s:s['overlayHidden'] and not s['localVoice']['visible'] and s['localVoice']['polling'] and s['localVoice']['summary']=='')
assert '/wizard-os-home/' in s['url'], s
print('PASS native-ready-after-onboarding',s['localVoice'])
cid=guest('docker ps -q --filter label=com.docker.compose.service=transcriber-engine').strip()
assert len(cid)==12 and all(c in '0123456789abcdef' for c in cid)
try:
    guest(f'docker pause {cid}; systemctl restart wizard-voice')
    s=wait(lambda s:'Preparing local voice' in s['localVoice']['summary'] and s['localVoice']['retryEnabled'])
    print('PASS native-preparing-not-ready',s['localVoice'])
    command('voice-retry')
    # Readback systemd is the authority, not the accepted HTTP status.
    print('systemd',guest('systemctl is-active wizard-voice').strip())
finally:
    guest(f'docker unpause {cid}')
s=wait(lambda s:not s['localVoice']['visible'] and s['localVoice']['summary']=='')
print('PASS native-retry-recovers',s['localVoice'])
# Remote here is the SAME disposable guest URL, never James\'s daily service.
command('connect http://127.0.0.1:48023/wizard-os-home/')
s=wait(lambda s:not s['localVoice']['visible'] and not s['localVoice']['polling'])
assert s['localVoice']['summary']=='',s
print('PASS remote-clears-local-voice')
time.sleep(6)
assert not state()['localVoice']['visible']
command('switch 0')
s=wait(lambda s:not s['localVoice']['visible'] and s['localVoice']['polling'] and s['localVoice']['summary']=='')
print('PASS local-restores-hidden-ready-status')
req=urllib.request.Request('http://127.0.0.1:48030/api/voice/retry',data=b'',headers={'Origin':'https://unrelated.example'},method='POST')
try:
    urllib.request.urlopen(req)
    raise AssertionError('cross-origin retry was allowed')
except urllib.error.HTTPError as e:
    assert e.code==403,e
print('PASS actual-guest-cross-origin-retry-rejected')
print('NATIVE_VOICE_OK')
