#!/bin/bash
# Update acceptance on Thales: install a Wizard OS image over a running, onboarded one (Wizard menu -> Install Wizard
# OS from File: the same unpack path as an update download). The disk must be kept: chats, installed apps and the
# onboarding state survive; only kernel/initrd/manifest change.
#   qa-update.sh <wizard-os-x.tar.xz> [evidence dir]
set -u
OS=${1:?wizard-os tar.xz}; EV=${2:-/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/evidence/update}
HERE="$(cd "$(dirname "$0")" && pwd)"
AS="$HOME/Library/Application Support/Wizard"; APP="$HOME/Applications/WizardNext/Wizard.app"
mkdir -p "$EV"; exec > >(tee "$EV/qa-update.log") 2>&1
U=http://127.0.0.1:47823
data() {
  echo "chats: $(curl -s -m 10 "$U/wizard/hermes/api/sessions?limit=200" | python3 -c "import json,sys;d=json.load(sys.stdin);s=d.get('sessions') or d.get('data') or [];print(len(s))" 2>/dev/null)"
  echo "apps: $(curl -s -m 10 "$U/wizard/v1/apps" | python3 -c "import json,sys;d=json.load(sys.stdin);print(sorted(a['id'] for a in d.get('apps',[])))" 2>/dev/null)"
  echo "onboarded: $(curl -s -m 5 http://127.0.0.1:47830/api/state | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['name'],d['done'])" 2>/dev/null)"
}
BEFORE=$(data); echo "$BEFORE"
ls -ls "$AS/os/disk.img"; DISK_BEFORE=$(du -k "$AS/os/disk.img" | cut -f1)
pgrep -x Wizard >/dev/null || { open "$APP"; sleep 5; }
t0=$(python3 -c 'import time;print(time.time())')
bash "$HERE/qa.sh" "install-file $OS"
while python3 -c "import time,sys;sys.exit(0 if time.time()-$t0<600 else 1)"; do
  sleep 1; /tmp/wizard-qa-post state 2>/dev/null; sleep 0.2
  python3 -c "import json,sys;d=json.load(open('/tmp/wizard-qa-state.json'));sys.exit(0 if (d['overlayHidden'] and d['loadedAt']>$t0) or d['title'].startswith(('Can','Wizard OS didn','Get Wizard')) else 1)" 2>/dev/null && break
done
python3 -c "import json,time;d=json.load(open('/tmp/wizard-qa-state.json'));print('update_to_window_s=%.1f'%(time.time()-$t0),'|',d['title'],'|',d['url'])"
ls -ls "$AS/os/"; DISK_AFTER=$(du -k "$AS/os/disk.img" | cut -f1)
echo "disk.img allocated KB before=$DISK_BEFORE after=$DISK_AFTER"
[ -e "$AS/os/disk-previous.img" ] && echo "UNEXPECTED: disk replaced (stack changed)"
sleep 20; AFTER=$(data); echo "$AFTER"
[ "$BEFORE" = "$AFTER" ] && echo "UPDATE_KEEPS_DISK_OK" || echo "UPDATE_DIFF"
