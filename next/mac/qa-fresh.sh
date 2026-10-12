#!/bin/bash
# Fresh-install acceptance on a real Mac (Thales), Wizard OS 0.2 stack:
#   wipe Wizard OS + prefs -> install Wizard.app from the DMG -> "On this Mac" -> "Keep files in ~/Wizard?" ->
#   download Wizard OS from a feed (local http server with the built image: the real download + SHA-256 path) ->
#   Wizard OS boots -> onboarding page in the window -> name + free brain + wake-up check -> first chat (opened through
#   the wizard-shell app, as Wizard UX does) -> wait for the agent's reply. Prints every timing.
#
#   qa-fresh.sh <Wizard-x.dmg> <wizard-os-x.tar.xz> [evidence dir]
set -u
DMG=${1:?dmg}; OS=${2:?wizard-os tar.xz}; EV=${3:-/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/evidence/fresh}
HERE="$(cd "$(dirname "$0")" && pwd)"
AS="$HOME/Library/Application Support/Wizard"
APP="$HOME/Applications/WizardNext/Wizard.app"
mkdir -p "$EV"; exec > >(tee "$EV/qa-fresh.log") 2>&1
now() { python3 -c 'import time;print(time.time())'; }
since() { python3 -c "import time;print('%.1f'%(time.time()-$1))"; }
state() { /tmp/wizard-qa-post state 2>/dev/null; sleep 0.2; python3 -c "import json;d=json.load(open('/tmp/wizard-qa-state.json'));print(d['overlayHidden'],'|',d['title'],'|',d['url'])" 2>/dev/null; }
bash "$HERE/qa.sh" state >/dev/null 2>&1   # compiles /tmp/wizard-qa-post

echo "== stop Wizard; wipe Wizard OS, logs, prefs and the files-folder choice"
pkill -x Wizard; pkill -TERM -f "Wizard Host.app/Contents/MacOS"
for i in $(seq 1 60); do pgrep -f "Wizard Host.app/Contents/MacOS" >/dev/null || break; sleep 1; done
rm -rf "$AS/os" "$AS/os-staging" "$AS/logs" "$AS/host-status.json" "$AS/files-folder.json"
defaults delete org.humanitylabs.wizard >/dev/null 2>&1 || true
mkdir -p "$AS"; touch "$AS/dev-shell"     # QA only: root shell into the guest (qa-guest.sh)

echo "== feed: serve $(basename "$OS") over local http"
FEED=$(mktemp -d); ln -s "$OS" "$FEED/$(basename "$OS")"
SHA=$(shasum -a 256 "$OS" | cut -d' ' -f1); BYTES=$(stat -f %z "$OS")
VER=$(basename "$OS" .tar.xz | sed 's/^wizard-os-//')
printf '{"version":"%s","url":"%s","sha256":"%s","bytes":%s}\n' "$VER" "$(basename "$OS")" "$SHA" "$BYTES" > "$FEED/latest.json"
(cd "$FEED" && exec python3 -m http.server 47999 --bind 127.0.0.1 >/dev/null 2>&1) & HTTPD=$!
trap 'kill $HTTPD 2>/dev/null' EXIT
echo "image $(basename "$OS") $BYTES bytes sha256 $SHA"

echo "== install the app from the DMG"
MNT=$(hdiutil attach -nobrowse -readonly "$DMG" | awk -F'\t' '/\/Volumes\//{print $NF}')
rm -rf "$APP"; mkdir -p "$(dirname "$APP")"; ditto "$MNT/Wizard.app" "$APP"; hdiutil detach -quiet "$MNT"
codesign --verify --deep --strict "$APP" && echo "codesign (ad-hoc) ok"; du -sh "$APP"
defaults write org.humanitylabs.wizard QAHooks -bool true
defaults write org.humanitylabs.wizard osFeedURL "http://127.0.0.1:47999/latest.json"

echo "== launch, On this Mac"
open "$APP"; sleep 3
bash "$HERE/qa.sh" choose-this-mac; sleep 2
echo "prompt: $(state)"; bash "$HERE/qa.sh" "snapshot $EV/1-files-folder-prompt.png"; sleep 1
echo "== Use ~/Wizard (t0)"
T0=$(now); bash "$HERE/qa.sh" files-folder
seen=""
while :; do
  s=$(state); [ "$s" != "$seen" ] && { echo "$(since $T0)s $s"; seen="$s"; }
  case "$s" in *"Setting up"*) [ -f "$EV/2-download.png" ] || bash "$HERE/qa.sh" "snapshot $EV/2-download.png";; esac
  case "$s" in True*) break;; *"didn"*|*"Get Wizard OS"*|*"Couldn"*) echo "FAIL: $s"; exit 1;; esac
  python3 -c "import time,sys;sys.exit(0 if time.time()-$T0<900 else 1)" || { echo "FAIL: timeout"; exit 1; }
  sleep 0.5
done
T_WINDOW=$(since $T0); echo "onboarding_in_window_s=$T_WINDOW"
grep -E "starting|ready|sharing" "$AS/logs/host.log" | tail -4
sleep 1; bash "$HERE/qa.sh" "snapshot $EV/3-onboarding.png"
ls -la "$HOME/Wizard"

echo "== onboarding: name, free brain, wake-up check, first chat"
B=http://127.0.0.1:47830; J=(-H content-type:application/json)
curl -s "${J[@]}" -XPOST $B/api/name -d '{"name":"Merlin"}' >/dev/null
t=$(now); curl -s -m 200 "${J[@]}" -XPOST $B/api/brain -d '{"kind":"free"}' | python3 -c "import json,sys;d=json.load(sys.stdin);print('brain:',(d.get('brain') or {}).get('label'),d.get('error',''))"; echo "brain_s=$(since $t)"
t=$(now); curl -s -m 300 -XPOST $B/api/verify | python3 -c "import json,sys;d=json.load(sys.stdin);print('wake-up reply:',d.get('reply') or d.get('error'))"; echo "verify_s=$(since $t)"
FIN=$(curl -s -m 60 -XPOST $B/api/finish); echo "finish: $FIN"
SID=$(echo "$FIN" | python3 -c "import json,sys;print(json.load(sys.stdin).get('firstSessionId') or '')")
[ -n "$SID" ] || { echo "FAIL: no first chat"; exit 1; }
U=http://127.0.0.1:47823
R=""
for i in $(seq 1 150); do
  R=$(curl -s -m 10 "$U/wizard/hermes/api/sessions/$SID/messages?limit=50" | python3 -c "
import json,sys
d=json.load(sys.stdin); ms=d.get('messages') if isinstance(d,dict) else d
txt=[m.get('content') for m in ms or [] if m.get('role')=='assistant' and isinstance(m.get('content'),str) and m.get('content').strip()]
print(txt[-1].replace(chr(10),' ') if txt else '')" 2>/dev/null)
  [ -n "$R" ] && break; sleep 2
done
T_CHAT=$(since $T0)
echo "first chat reply: $R"
[ -n "$R" ] && echo "first_boot_to_first_chat_reply_s=$T_CHAT" || { echo "FAIL: no reply in first chat"; exit 1; }
curl -s -o /dev/null -w "front door after onboarding: %{http_code} -> %{redirect_url}\n" $B/
bash "$HERE/qa.sh" reload; sleep 8; echo "window: $(state)"; bash "$HERE/qa.sh" "snapshot $EV/4-wizard-ux.png"; sleep 1
echo "$SID" > "$EV/first-session-id"
echo "QA_FRESH_OK"
