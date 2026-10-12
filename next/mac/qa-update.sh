#!/bin/bash
# Same-stack archive update: keep the actual disk inode, chats, apps and onboarding.
# qa-update.sh <wizard-os.tar.xz> [evidence dir]; use only an isolated QA Wizard.
set -euo pipefail
OS=${1:?wizard-os tar.xz}; EV=${2:-$HOME/wizard-qa/update}
HERE="$(cd "$(dirname "$0")" && pwd)"
AS="$HOME/Library/Application Support/Wizard"; APP="$HOME/Applications/WizardNext/Wizard.app"
mkdir -p "$EV"; exec > >(tee "$EV/qa-update.log") 2>&1
# Retained QA disks/checkpoints coexist with the incoming factory extraction.
# Reject low headroom before launching tar; do not consume the host's last bytes.
python3 - "$AS" <<'PY'
import shutil,sys
free=shutil.disk_usage(sys.argv[1]).free
need=16 << 30
if free < need:
    raise SystemExit(f'QA_UPDATE_BLOCKED_CAPACITY: {free} bytes free; require {need} bytes')
PY
U=http://127.0.0.1:47823
snapshot() {
  python3 - "$U" <<'PY'
import json,sys,urllib.request
u=sys.argv[1]
def get(url):
    with urllib.request.urlopen(url,timeout=20) as r: return json.load(r)
s=get(u+'/wizard/hermes/api/sessions?limit=200')
a=get(u+'/wizard/v1/apps'); o=get('http://127.0.0.1:47830/api/state')
sessions=s.get('data') or s.get('sessions') or []
assert sessions and a.get('apps') and o['done'], 'missing QA state'
print(json.dumps({'sessions':sorted(x['id'] for x in sessions),
                  'apps':sorted(x['id'] for x in a['apps']),
                  'onboarding':{k:o[k] for k in ['name','done','brain']}},sort_keys=True))
PY
}
open "$APP"; sleep 3
snapshot > "$EV/before.json"; cat "$EV/before.json"
DISK_BEFORE=$(stat -f '%d:%i:%z' "$AS/os/disk.img")
[ ! -e "$AS/os/disk-previous.img" ] || { echo 'FAIL: pre-existing disk-previous.img'; exit 1; }
bash "$HERE/qa.sh" state >/dev/null
t0=$(python3 -c 'import time;print(time.time())')
bash "$HERE/qa.sh" "install-file $OS"
ok=0; reloaded=0
for i in $(seq 1 600); do
  sleep 1
  # install-file is a QA hook; an already installed guest has no setup callback.
  # Wait for the verified installer move, then explicitly reopen the existing guest.
  if [ "$reloaded" = 0 ] && python3 - "$AS" "$t0" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1]); m=p/'os/manifest.json'
sys.exit(0 if m.exists() and m.stat().st_ctime>float(sys.argv[2]) and not (p/'os-staging').exists() else 1)
PY
  then /tmp/wizard-qa-post reload; reloaded=1; fi
  /tmp/wizard-qa-post state; sleep 0.2
  if python3 - "$t0" <<'PY'
import json,sys
d=json.load(open('/tmp/wizard-qa-state.json'))
sys.exit(0 if d['overlayHidden'] and d['loadedAt']>float(sys.argv[1]) else 1)
PY
  then ok=1; break; fi
done
[ "$ok" = 1 ] || { echo 'FAIL: update did not load the guest window'; exit 1; }
cp /tmp/wizard-qa-state.json "$EV/window.json"
DISK_AFTER=$(stat -f '%d:%i:%z' "$AS/os/disk.img")
echo "disk before=$DISK_BEFORE after=$DISK_AFTER"
[ "$DISK_BEFORE" = "$DISK_AFTER" ] && [ ! -e "$AS/os/disk-previous.img" ] || { echo 'FAIL: disk replaced'; exit 1; }
sleep 20; snapshot > "$EV/after.json"; cat "$EV/after.json"
cmp "$EV/before.json" "$EV/after.json" || { echo UPDATE_DIFF; exit 1; }
echo UPDATE_KEEPS_DISK_OK
