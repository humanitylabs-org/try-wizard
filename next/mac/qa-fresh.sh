#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Fresh-install acceptance on a real Mac (Thales), Wizard OS 0.2 stack:
#   wipe Wizard OS + prefs -> install Wizard.app from the DMG -> "On this Mac" -> "Keep files in ~/Wizard?" ->
#   download Wizard OS from a feed (local http server with the built image: the real download + SHA-256 path) ->
#   Wizard OS boots -> onboarding page in the window -> name + free brain + wake-up check -> first chat (opened through
#   the wizard-shell app, as Wizard UX does) -> wait for the agent's reply. Prints every timing.
#
#   qa-fresh.sh <Wizard-x.dmg> <wizard-os-x.tar.xz> [evidence dir]     (env FEED_URL / FEED_DIR: see feed below)
set -u
DMG=${1:?dmg}; OS=${2:?wizard-os tar.xz}; EV=${3:-$WIZARD_WORK_ROOT/Projects/wizard-desktop/wizard-os-020/evidence/fresh}
HERE="$(cd "$(dirname "$0")" && pwd)"
AS="$HOME/Library/Application Support/Wizard"
APP="$HOME/Applications/WizardNext/Wizard.app"
mkdir -p "$EV"; exec > >(tee "$EV/qa-fresh.log") 2>&1
now() { python3 -c 'import time;print(time.time())'; }
since() { python3 -c "import time;print('%.1f'%(time.time()-$1))"; }
state() { /tmp/wizard-mvp-qa-post state 2>/dev/null; sleep 0.2; python3 -c "import json;d=json.load(open('/tmp/wizard-mvp-qa-state.json'));print(d['overlayHidden'],'|',d['title'],'|',d['url'])" 2>/dev/null; }
bash "$HERE/qa.sh" state >/dev/null 2>&1
# The app writes snapshots to /tmp (writing to an external volume would stop on a macOS privacy prompt).
snap() { bash "$HERE/qa.sh" "snapshot /tmp/wq-$1.png"; sleep 2; mv -f "/tmp/wq-$1.png" "$EV/$1.png" 2>/dev/null; }

echo "== stop Wizard; wipe Wizard OS, logs, prefs and the files-folder choice"
pkill -x Wizard; pkill -TERM -f "Wizard Host.app/Contents/MacOS"
for i in $(seq 1 60); do pgrep -f "Wizard Host.app/Contents/MacOS" >/dev/null || break; sleep 1; done
rm -rf "$AS/os" "$AS/os-staging" "$AS/logs" "$AS/host-status.json" "$AS/files-folder.json"
defaults delete org.humanitylabs.wizard.mvp >/dev/null 2>&1 || true
mkdir -p "$AS"; touch "$AS/dev-shell"     # QA only: root shell into the guest (qa-guest.sh)

# Feed: FEED_URL=<https://…/latest.json> downloads from a real host (no local server); FEED_DIR=<dir> serves an
# existing feed folder (split parts + latest.json from split-release.sh); otherwise serve the single archive.
FEED_URL=${FEED_URL:-}
if [ -z "$FEED_URL" ]; then
  if [ -n "${FEED_DIR:-}" ]; then
    FEED=$FEED_DIR; echo "== feed: serve $FEED over local http"
  else
    echo "== feed: serve $(basename "$OS") over local http"
    FEED=$(mktemp -d); ln -s "$OS" "$FEED/$(basename "$OS")"
    SHA=$(shasum -a 256 "$OS" | cut -d' ' -f1); BYTES=$(stat -f %z "$OS")
    VER=$(basename "$OS" .tar.xz | sed 's/^wizard-os-//')
    INST=$(tar -xqOf "$OS" manifest.json 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('installBytes') or 'null')" 2>/dev/null || echo null)
    printf '{"version":"%s","url":"%s","sha256":"%s","bytes":%s,"installBytes":%s}\n' "$VER" "$(basename "$OS")" "$SHA" "$BYTES" "$INST" > "$FEED/latest.json"
  fi
  (cd "$FEED" && exec python3 -m http.server 47999 --bind 127.0.0.1 >/dev/null 2>&1) & HTTPD=$!
  trap 'kill $HTTPD 2>/dev/null' EXIT
  FEED_URL=http://127.0.0.1:47999/latest.json
  for _ in $(seq 1 40); do curl -fsS -o /dev/null -m 2 "$FEED_URL" && break; sleep 0.25; done   # server up before the app asks
fi
echo "feed loaded"; curl -fsS -m 20 "$FEED_URL" | python3 -c 'import json,sys; d=json.load(sys.stdin); print({k:d.get(k) for k in ("version","bytes","installBytes","background")})'; df -h "$HOME" | tail -1

echo "== install the app from the DMG"
MNT=$(hdiutil attach -nobrowse -readonly "$DMG" | awk -F'\t' '/\/Volumes\//{print $NF}')
rm -rf "$APP"; mkdir -p "$(dirname "$APP")"; ditto "$MNT/Wizard.app" "$APP"; hdiutil detach -quiet "$MNT"
codesign --verify --deep --strict "$APP" && echo "codesign (ad-hoc) ok"; du -sh "$APP"
defaults write org.humanitylabs.wizard.mvp QAHooks -bool true
defaults write org.humanitylabs.wizard.mvp osFeedURL "$FEED_URL"

echo "== launch, On this Mac"
if [ "${QA_SSH_LAUNCH:-0}" = 1 ]; then
  # Explicit isolated external-volume QA: SSH owns the removable-volume grant.
  # This is not proof of Finder/TCC consent on a tester's Mac.
  "$APP/Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host" > "$EV/direct-host.log" 2>&1 &
  "$APP/Contents/MacOS/Wizard" > "$EV/direct-app.log" 2>&1 &
else
  open "$APP"
fi
sleep 3
bash "$HERE/qa.sh" choose-this-mac; sleep 2
echo "prompt: $(state)"; snap 1-files-folder-prompt; sleep 1
echo "== Use ~/Wizard (t0)"
T0=$(now); bash "$HERE/qa.sh" files-folder
seen=""
while :; do
  s=$(state); [ "$s" != "$seen" ] && { echo "$(since $T0)s $s"; seen="$s"; }
  case "$s" in *"Setting up"*) [ -f "$EV/2-download.png" ] || snap 2-download;; esac
  [ $(( ${PROG_N:=0} % 60 )) = 0 ] && python3 -c "import json;print('   progress:', json.load(open('/tmp/wizard-mvp-qa-state.json')).get('subtitle',''))" 2>/dev/null; PROG_N=$((PROG_N+1))
  case "$s" in True*) break;; *"didn"*|*"Get Wizard OS"*|*"Couldn"*) echo "FAIL: $s"; exit 1;; esac
  python3 -c "import time,sys;sys.exit(0 if time.time()-$T0<${QA_TIMEOUT:-900} else 1)" || { echo "FAIL: timeout"; exit 1; }
  sleep 0.5
done
T_WINDOW=$(since $T0); echo "onboarding_in_window_s=$T_WINDOW"
grep -E "starting|ready|sharing" "$AS/logs/host.log" | tail -4
sleep 1; snap 3-onboarding
ls -la "$HOME/Wizard"

echo "== onboarding: name, free brain, wake-up check, first chat"
B=http://127.0.0.1:48030; J=(-H content-type:application/json)
curl -s "${J[@]}" -XPOST $B/api/name -d '{"name":"Merlin"}' >/dev/null
t=$(now); curl -s -m 200 "${J[@]}" -XPOST $B/api/brain -d '{"kind":"free"}' | python3 -c "import json,sys;d=json.load(sys.stdin);print('brain:',(d.get('brain') or {}).get('label'),d.get('error',''))"; echo "brain_s=$(since $t)"
t=$(now); curl -s -m 300 -XPOST $B/api/verify | python3 -c "import json,sys;d=json.load(sys.stdin);print('wake-up reply:',d.get('reply') or d.get('error'))"; echo "verify_s=$(since $t)"
TF=$(now); FIN=$(curl -s -m 60 -XPOST $B/api/finish); echo "finish: $FIN"
SID=$(echo "$FIN" | python3 -c "import json,sys;print(json.load(sys.stdin).get('firstSessionId') or '')")
[ -n "$SID" ] || { echo "FAIL: no first chat"; exit 1; }
U=http://127.0.0.1:48023
R=""
for i in $(seq 1 150); do
  R=$(curl -s -m 10 "$U/wizard/hermes/api/sessions/$SID/messages?limit=50" | python3 -c "
import json,sys
d=json.load(sys.stdin); ms=(d.get('data') or d.get('messages')) if isinstance(d,dict) else d
txt=[m.get('content') for m in ms or [] if m.get('role')=='assistant' and isinstance(m.get('content'),str) and m.get('content').strip()]
print(txt[-1].replace(chr(10),' ') if txt else '')" 2>/dev/null)
  [ -n "$R" ] && break; sleep 2
done
T_CHAT=$(since $T0); T_REPLY=$(since $TF)
echo "first chat reply: $R"
[ -n "$R" ] && echo "first_chat_reply_after_finish_s=$T_REPLY first_launch_to_first_chat_reply_s=$T_CHAT (includes the scripted onboarding steps)" || { echo "FAIL: no reply in first chat"; exit 1; }
curl -s -o /dev/null -w "front door after onboarding: %{http_code} -> %{redirect_url}\n" $B/
bash "$HERE/qa.sh" reload; sleep 8; echo "window: $(state)"; snap 4-wizard-ux; sleep 1
echo "$SID" > "$EV/first-session-id"
echo "QA_FRESH_OK"
