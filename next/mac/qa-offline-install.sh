#!/bin/bash
# Fresh file-install QA with feed unavailable; save/restore all existing QA support and preferences.
# WIZARD_QA_ALLOW_STATE_MUTATION=1 qa-offline-install.sh <archive> <evidence dir>
set -euo pipefail
[ "${WIZARD_QA_ALLOW_STATE_MUTATION:-}" = 1 ] || { echo 'Explicit isolated-QA opt-in required'; exit 1; }
OS=${1:?archive}; EV=${2:?evidence dir}; HERE="$(cd "$(dirname "$0")" && pwd)"
AS="$HOME/Library/Application Support/Wizard"; APP="$HOME/Applications/WizardNext/Wizard.app"
SAVED="$AS-recovered-saved-$(date +%s)"; RETAINED="$AS-recovered-offline-$(date +%s)"
mkdir -p "$EV"; exec > >(tee "$EV/qa-offline-install.log") 2>&1
stop_qa() {
  python3 - "$APP" <<'PY'
import os,signal,subprocess,sys,time
prefix=sys.argv[1]+'/Contents/'
rows=subprocess.check_output(['ps','-ax','-o','pid=,command='],text=True).splitlines()
pids=[]
for line in rows:
    pid,cmd=line.strip().split(None,1)
    if cmd.startswith(prefix) and ('/MacOS/Wizard' in cmd):
        os.kill(int(pid),signal.SIGTERM); pids.append(int(pid))
for i in range(90):
    live=[]
    for pid in pids:
        try: os.kill(pid,0); live.append(pid)
        except ProcessLookupError: pass
    if not live: break
    time.sleep(1)
else: raise SystemExit('QA processes did not stop; refusing state move')
PY
}
stop_qa
defaults export org.humanitylabs.wizard "$EV/preferences-before.plist"
[ ! -e "$SAVED" ] && [ ! -e "$RETAINED" ]
mv "$AS" "$SAVED"
printf '%s\n' "$SAVED" "$RETAINED" > "$EV/state-paths.txt"
restore() {
  rc=$?; trap - EXIT
  stop_qa || { echo "RESTORE_BLOCKED: saved state at $SAVED"; exit 1; }
  [ ! -e "$AS" ] || mv "$AS" "$RETAINED"
  mv "$SAVED" "$AS"
  defaults import org.humanitylabs.wizard "$EV/preferences-before.plist"
  open "$APP"
  echo "QA_STATE_RESTORED (offline state retained at $RETAINED)"
  exit "$rc"
}
trap restore EXIT
mkdir -p "$AS"; touch "$AS/dev-shell"
defaults delete org.humanitylabs.wizard >/dev/null 2>&1 || true
defaults write org.humanitylabs.wizard QAHooks -bool true
open "$APP"; sleep 3
bash "$HERE/qa.sh" choose-this-mac-offline
sleep 2; /tmp/wizard-qa-post "files-folder $EV/media-qa"
# Wait for the feed-unavailable screen, not merely for an elapsed delay.
for i in $(seq 1 60); do
  /tmp/wizard-qa-post state; sleep 1
  python3 -c 'import json,sys; d=json.load(open("/tmp/wizard-qa-state.json"));sys.exit(0 if d["title"]=="Get Wizard OS" else 1)' && break
done
python3 -c 'import json;d=json.load(open("/tmp/wizard-qa-state.json"));assert d["title"]=="Get Wizard OS",d;print("FEED_UNAVAILABLE_OK",d["title"])'
cp /tmp/wizard-qa-state.json "$EV/feed-unavailable.json"
python3 - "$EV" <<'PY'
import json,pathlib,sys,tarfile
p=pathlib.Path(sys.argv[1]); b=p/'bad'; b.mkdir(exist_ok=True)
(b/'rootfs.img').write_bytes(b'corrupt QA data\n')
(b/'manifest.json').write_text(json.dumps({'files':{'rootfs.img':'0'*64}}))
with tarfile.open(p/'wizard-os-bad.tar.xz','w:xz') as t:
    for name in ['manifest.json','rootfs.img']: t.add(b/name,arcname=name)
PY
/tmp/wizard-qa-post "install-file $EV/wizard-os-bad.tar.xz"; sleep 4
/tmp/wizard-qa-post state; sleep 1
python3 -c 'import json;d=json.load(open("/tmp/wizard-qa-state.json"));assert "valid Wizard OS image" in d["subtitle"],d;print("CORRUPT_HASH_REJECTED_OK",d["subtitle"])'
[ ! -e "$AS/os/disk.img" ]
cp /tmp/wizard-qa-state.json "$EV/corrupt-rejected.json"
t0=$(python3 -c 'import time;print(time.time())')
/tmp/wizard-qa-post "install-file $OS"
ok=0
for i in $(seq 1 600); do
  /tmp/wizard-qa-post state; sleep 1
  if python3 - "$t0" <<'PY'
import json,sys
d=json.load(open('/tmp/wizard-qa-state.json'))
sys.exit(0 if d['overlayHidden'] and d['loadedAt']>float(sys.argv[1]) else 1)
PY
  then ok=1; break; fi
done
[ "$ok" = 1 ] || { echo 'FAIL: file install did not load window'; exit 1; }
cp /tmp/wizard-qa-state.json "$EV/offline-window.json"
curl -fsS http://127.0.0.1:47830/healthz
# The factory script must match the corrected source, not a previous live hotpatch.
bash "$HERE/qa-guest.sh" 'cat /opt/wizard/bin/wizard-media' > "$EV/installed-wizard-media"
cmp "$HERE/../guest/overlay/opt/wizard/bin/wizard-media" "$EV/installed-wizard-media"
bash "$HERE/qa-guest.sh" 'set -e; sudo -u wizard sh -c "printf uid1000 > /home/wizard/runtipi/media/Inbox/recovered-uid1000.txt"; sudo -iu wizard env XDG_RUNTIME_DIR=/run/user/1000 docker exec -u 0 files_wizardapps-files-1 sh -c "id; printf filesroot > /srv/Inbox/recovered-files-root.txt"; findmnt -T /home/wizard/runtipi/app-data; findmnt -T /home/wizard/runtipi/media; sudo -iu wizard env XDG_RUNTIME_DIR=/run/user/1000 docker inspect files_wizardapps-files-1 --format "{{json .Mounts}}"; test "$(stat -c %d /home/wizard/runtipi/app-data)" = "$(stat -c %d /)"; test "$(stat -c %d /home/wizard/runtipi/media)" != "$(stat -c %d /)"; echo FINAL_ARCHIVE_MEDIA_OK' | tee "$EV/media-check.log"
grep -q FINAL_ARCHIVE_MEDIA_OK "$EV/media-check.log"
[ "$(cat "$EV/media-qa/Inbox/recovered-uid1000.txt")" = uid1000 ]
[ "$(cat "$EV/media-qa/Inbox/recovered-files-root.txt")" = filesroot ]
echo MAC_VISIBLE_WRITES_OK
# 'On another computer' uses the disposable QA guest address, never a live agent.
/tmp/wizard-qa-post 'connect http://127.0.0.1:47823/wizard-ux/'
sleep 8; /tmp/wizard-qa-post state; sleep 1
python3 -c 'import json;d=json.load(open("/tmp/wizard-qa-state.json"));assert d["overlayHidden"] and d["active"]==1 and d["url"].startswith("http://127.0.0.1:47823/wizard-ux/"),d;print("ANOTHER_COMPUTER_LOCAL_QA_OK",d["url"])'
cp /tmp/wizard-qa-state.json "$EV/another-computer.json"
echo QA_OFFLINE_FINAL_ARCHIVE_OK
