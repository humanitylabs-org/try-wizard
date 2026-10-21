#!/usr/bin/env python3
"""Thales-only isolated QA guest: install owned fixes, prove interrupted voice recovery.
Run under $WIZARD_WORK_ROOT/AndroidBuilds/worker.lock. No daily services touched.
"""
import base64
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVERLAY = HERE.parent/'guest/overlay'

def guest(script):
    result = subprocess.run(['bash', str(HERE/'qa-guest.sh'), script], capture_output=True, text=True, timeout=300)
    print(result.stdout, flush=True)
    if result.returncode or 'VOICE_RECOVERY_FAILED' in result.stdout:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout

commands=['set -e', "trap 'echo VOICE_RECOVERY_FAILED' ERR"]
for rel in ['opt/wizard/bin/wizard-apps', 'opt/wizard/voice/start.sh', 'etc/systemd/system/wizard-voice.service']:
    data=base64.b64encode((OVERLAY/rel).read_bytes()).decode()
    commands.append(f"printf %s '{data}' | base64 -d > /{rel}")
commands.extend(['chmod 755 /opt/wizard/bin/wizard-apps /opt/wizard/voice/start.sh','systemctl daemon-reload','echo OWNED_FIXES_LOADED'])
assert 'OWNED_FIXES_LOADED' in guest('\n'.join(commands))

script=r'''set -e
trap 'echo VOICE_RECOVERY_FAILED; docker unpause "$cid" >/dev/null 2>&1 || true' ERR
cid=$(docker ps -q --filter label=com.docker.compose.service=transcriber-engine)
test -n "$cid"
# Installed app and stale ready marker must not produce readiness while the engine cannot answer.
touch /var/lib/wizard/voice-installed
docker pause "$cid"
trap 'docker unpause "$cid" >/dev/null 2>&1 || true' EXIT
systemctl restart wizard-voice
sleep 12
python3 -c 'import json; d=json.load(open("/var/lib/wizard/voice.json")); assert d["state"] != "ready",d; print("PASS installed-but-unavailable",d)'
systemctl stop wizard-voice
systemctl start wizard-voice
sleep 2
python3 -c 'import json; d=json.load(open("/var/lib/wizard/voice.json")); assert d["state"] != "ready",d; print("PASS interrupted-preparation-restart",d)'
docker unpause "$cid"
trap - EXIT
for i in $(seq 1 40); do
  python3 -c 'import json; exit(0 if json.load(open("/var/lib/wizard/voice.json"))["state"]=="ready" else 1)' && break
  sleep 2
done
python3 -c 'import json; d=json.load(open("/var/lib/wizard/voice.json")); assert d["state"]=="ready",d; print("PASS readiness-recovered",d)'
# Recreate a real interrupted small pinned model-file download; retain original as checkpoint.
p=/home/wizard/runtipi/app-data/wizardapps/transcriber/data/voice/models/parakeet-tdt-0.6b-v2-int8
systemctl stop wizard-voice
docker stop "$cid" >/dev/null
cp -p "$p/vocab.txt" /var/lib/wizard/qa-vocab-checkpoint
python3 - "$p" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); v=p/'vocab.txt'; b=v.read_bytes()
(p/'vocab.txt.part').write_bytes(b[:128]); v.unlink(); (p/'vocab.txt.ok').unlink(missing_ok=True)
PY
chown 1000:1000 "$p/vocab.txt.part"
docker start "$cid" >/dev/null
systemctl start wizard-voice
python3 - <<'PY'
import time,json
end=time.monotonic()+120
time.sleep(2)
while time.monotonic()<end:
    if json.load(open('/var/lib/wizard/voice.json'))['state']=='ready': break
    time.sleep(2)
else: raise AssertionError('voice did not recover within 120 seconds')
PY
python3 - "$p" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]); d=json.load(open('/var/lib/wizard/voice.json'))
assert d['state']=='ready',d
assert (p/'vocab.txt').read_bytes()==Path('/var/lib/wizard/qa-vocab-checkpoint').read_bytes()
assert not (p/'vocab.txt.part').exists()
print('PASS real-pinned-model-partial-download-recovery',d)
PY
echo VOICE_RECOVERY_OK
'''
assert 'VOICE_RECOVERY_OK' in guest(script)
