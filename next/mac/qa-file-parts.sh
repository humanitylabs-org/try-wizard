#!/bin/bash
# File-install acceptance for split Wizard OS archives (Choose Downloaded File… with every part selected).
#   Phase 1: parts on an external drive. macOS holds the read until the user allows "Removable Volumes";
#            the app must say so (instead of sitting on "Checking…") and must not touch the current OS.
#   Phase 2: the same parts in an internal folder install Wizard OS and boot it.
# Wipes the QA Wizard OS (back it up first). Isolated QA only.
#   WIZARD_QA_ALLOW_STATE_MUTATION=1 qa-file-parts.sh <Wizard.dmg> <feed dir on external drive> <evidence dir>
set -uo pipefail
[ "${WIZARD_QA_ALLOW_STATE_MUTATION:-}" = 1 ] || { echo 'Explicit isolated-QA opt-in required'; exit 1; }
DMG=${1:?dmg}; EXT=${2:?feed dir with parts}; EV=${3:?evidence dir}
HERE="$(cd "$(dirname "$0")" && pwd)"
AS="$HOME/Library/Application Support/Wizard"; APP="$HOME/Applications/WizardNext/Wizard.app"
INT="$HOME/.cache/wizard-qa-parts"
mkdir -p "$EV"; exec > >(tee "$EV/qa-file-parts.log") 2>&1
st() { /tmp/wizard-qa-post state 2>/dev/null; sleep 0.3; python3 -c "import json;d=json.load(open('/tmp/wizard-qa-state.json'));print(d['overlayHidden'],'|',d['title'],'|',d['subtitle'].replace(chr(10),' '),'|',d['url'])" 2>/dev/null; }
stop() { pkill -x Wizard; pkill -TERM -f "Wizard Host.app/Contents/MacOS"; for i in $(seq 1 60); do pgrep -f "$APP/Contents/MacOS" >/dev/null || break; sleep 1; done; }
fresh_app() {
  stop; rm -rf "$AS/os" "$AS/os-staging" "$AS/logs" "$AS/host-status.json"
  defaults delete org.humanitylabs.wizard >/dev/null 2>&1 || true
  defaults write org.humanitylabs.wizard QAHooks -bool true
  defaults write org.humanitylabs.wizard permissionWaitSeconds -float 4
  mkdir -p "$AS"; touch "$AS/dev-shell"
  open "$APP"; sleep 3; bash "$HERE/qa.sh" state >/dev/null 2>&1
  bash "$HERE/qa.sh" choose-this-mac-offline; sleep 2
  /tmp/wizard-qa-post "files-folder $HOME/Wizard"; sleep 6
  echo "start: $(st)"
}
stop; rm -rf "$AS/os" "$AS/os-staging"   # this QA replaces the local QA Wizard OS; back it up first
python3 - "$AS" <<'PY' || exit 1
import shutil,sys,os
os.makedirs(sys.argv[1],exist_ok=True)
free=shutil.disk_usage(sys.argv[1]).free
print('free bytes', free)
if free < 19 << 30: raise SystemExit('QA_FILE_PARTS_BLOCKED_CAPACITY: need 16 GiB + room for an internal copy of the parts')
PY
P0=$(ls "$EXT"/*.part00); P1=$(ls "$EXT"/*.part01)
echo "== install app from $DMG"
MNT=$(hdiutil attach -nobrowse -readonly "$DMG" | awk -F'\t' '/\/Volumes\//{print $NF}')
stop; rm -rf "$APP"; mkdir -p "$(dirname "$APP")"; ditto "$MNT/Wizard.app" "$APP"; hdiutil detach -quiet "$MNT"
codesign --verify --deep --strict "$APP" && echo "codesign ok $(defaults read "$APP/Contents/Info" CFBundleShortVersionString)"

echo "== phase 0: a missing part is refused before anything is staged"
fresh_app
/tmp/wizard-qa-post "install-file $P1"
for i in $(seq 1 20); do s=$(st); case "$s" in *"Part 00 is missing"*) break;; esac; sleep 0.5; done
echo "missing part: $s"
case "$s" in *"Part 00 is missing"*) ;; *) echo "FAIL: missing part not refused"; exit 1;; esac
[ -e "$AS/os-staging" ] && { echo "FAIL: staging created for a refused selection"; exit 1; }
echo "MISSING_PART_REFUSED_OK"

echo "== phase 1: parts on $(df "$EXT" | tail -1 | awk '{print $NF}')"
fresh_app
T=$(python3 -c 'import time;print(time.time())')
/tmp/wizard-qa-post "install-file $P1|$P0"      # reversed on purpose: the app must sort parts by name
ok1=""
for i in $(seq 1 40); do
  s=$(st); case "$s" in *"Waiting for macOS to let Wizard read files on"*) ok1="$s"; break;; esac; sleep 0.5
done
echo "after $(python3 -c "import time;print('%.1f'%(time.time()-$T))")s: $(st)"
bash "$HERE/qa.sh" "snapshot /tmp/wq-permission.png"; sleep 2; mv -f /tmp/wq-permission.png "$EV/permission-wait.png" 2>/dev/null
stop; pkill -f "tar -xJf - -C $AS/os-staging" 2>/dev/null
[ -e "$AS/os" ] && { echo "FAIL: current OS changed during a held read"; exit 1; }
rm -rf "$AS/os-staging"
[ -n "$ok1" ] && echo "EXTERNAL_PERMISSION_MESSAGE_OK" || { echo "FAIL: no permission message"; exit 1; }

echo "== phase 2: the same parts from an internal folder"
rm -rf "$INT"; mkdir -p "$INT"; cp "$P0" "$P1" "$INT/"
fresh_app
T=$(python3 -c 'import time;print(time.time())')
/tmp/wizard-qa-post "install-file $INT/$(basename "$P1")|$INT/$(basename "$P0")"
seen=""
while :; do
  s=$(st); [ "$s" != "$seen" ] && { echo "$(python3 -c "import time;print('%.1f'%(time.time()-$T))")s $s"; seen="$s"; }
  case "$s" in True*) break;; *"didn"*|*"Couldn"*|*"isn't a valid"*|*"failed"*) echo "FAIL: $s"; rm -rf "$INT"; exit 1;; esac
  python3 -c "import time,sys;sys.exit(0 if time.time()-$T<900 else 1)" || { echo "FAIL: timeout"; rm -rf "$INT"; exit 1; }
  sleep 1
done
rm -rf "$INT"
curl -fsS -m 10 http://127.0.0.1:47830/healthz && echo
python3 - "$AS/os/manifest.json" <<'PY'
import json,sys; m=json.load(open(sys.argv[1])); print('installed', m.get('version'), m.get('stack'), m.get('sourceCommit'))
PY
echo "QA_FILE_PARTS_OK"
