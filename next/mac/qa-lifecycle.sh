#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Lifecycle acceptance on Thales (WizardOS 0.2 stack). Assumes qa-fresh.sh ran (installed + onboarded).
#   1. close the window: WizardOS keeps running        2. warm open x3 (WizardOS running)
#   3. cold open x2 (WizardOS stopped)                  4. chats, installed apps and files survive all of it
#   5. memory: VM process footprint, guest free -m, per-container memory
set -u
EV=${1:-$WIZARD_WORK_ROOT/Projects/wizard-desktop/wizard-os-020/evidence/lifecycle}
HERE="$(cd "$(dirname "$0")" && pwd)"
AS="$HOME/Library/Application Support/Wizard"
APP="$HOME/Applications/WizardNext/Wizard.app"
mkdir -p "$EV"; exec > >(tee "$EV/qa-lifecycle.log") 2>&1
bash "$HERE/qa.sh" state >/dev/null 2>&1
# The app writes snapshots to /tmp (writing to an external volume would stop on a macOS privacy prompt).
snap() { bash "$HERE/qa.sh" "snapshot /tmp/wq-$1.png"; sleep 2; mv -f "/tmp/wq-$1.png" "$EV/$1.png" 2>/dev/null; }
now() { python3 -c 'import time;print(time.time())'; }
# Wizard's VM = the Virtualization XPC process started most recently (Colima's is older).
vmproc() { pgrep -n -f "com.apple.Virtualization.VirtualMachine"; }
appopen_until_ux() { # seconds from `open` until the Wizard UX page finished loading in the window
  local t0=$(now); open "$APP"
  rm -f /tmp/wizard-mvp-qa-state.json
  while python3 -c "import time,sys;sys.exit(0 if time.time()-$t0<240 else 1)"; do
    sleep 0.1; /tmp/wizard-mvp-qa-post state 2>/dev/null; sleep 0.05
    python3 -c "import json,sys;d=json.load(open('/tmp/wizard-mvp-qa-state.json'));sys.exit(0 if (d['overlayHidden'] and d['loadedAt']>$t0 and '/wizard-ux/' in d['url']) or d['title'].startswith(('Can','WizardOS didn')) else 1)" 2>/dev/null && break
  done
  python3 -c "import json;d=json.load(open('/tmp/wizard-mvp-qa-state.json'));print('%.2f'%(d['loadedAt']-$t0) if d['overlayHidden'] and d['loadedAt'] else 'FAIL '+d['title']+' / '+d['subtitle'])"
}
hostcmd() {
  cat > /tmp/hc.swift <<EOF
import Foundation
DistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.mvp.host.command"), object: CommandLine.arguments[1], userInfo: nil, deliverImmediately: true)
RunLoop.main.run(until: Date().addingTimeInterval(0.3))
EOF
  [[ -x /tmp/hc ]] || xcrun swiftc -O /tmp/hc.swift -o /tmp/hc 2>/dev/null; /tmp/hc "$1"
}
mem() {
  local p=$(vmproc)
  echo "vm_process_rss_mb=$(( $(ps -o rss= -p ${p:-1}) / 1024 ))"
  [[ -n "$p" ]] && footprint "$p" 2>/dev/null | grep -E "Footprint" | head -1
  bash "$HERE/qa-guest.sh" 'free -m | sed -n 1,2p; docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" | sort' 2>/dev/null
}
snapshot_data() { # chats, installed apps, files: compared before/after
  local U=http://127.0.0.1:48023
  echo "chats: $(curl -s -m 10 "$U/wizard/hermes/api/sessions?limit=200" | python3 -c "import json,sys;d=json.load(sys.stdin);s=d.get('data') or d.get('sessions') or [];print(len(s), sorted(x.get('id') for x in s)[:3])" 2>/dev/null)"
  echo "apps: $(curl -s -m 10 "$U/wizard/v1/apps" | python3 -c "import json,sys;d=json.load(sys.stdin);print(sorted(a['id'] for a in d.get('apps',[])))" 2>/dev/null)"
  echo "files: $(cd "$HOME/Wizard" 2>/dev/null && ls -1 | tr '\n' ' ')"
}
mkdir -p "$HOME/Wizard/Documents"; date > "$HOME/Wizard/Documents/lifecycle-marker.txt"
BEFORE=$(snapshot_data); echo "$BEFORE"

echo "== 1. window closed -> WizardOS keeps running"
osascript -e 'tell application "Wizard" to quit' 2>/dev/null; sleep 2
pgrep -x Wizard >/dev/null && echo "app still running" || echo "app quit"
grep state "$AS/host-status.json"
curl -s -m 3 http://127.0.0.1:48030/healthz && echo " <- front door answering with the app closed"
curl -s -m 3 http://127.0.0.1:48023/wizard/health | head -c 120; echo " <- wizard-shell answering"
mem

echo "== 2. warm open (WizardOS running)"
for n in 1 2 3; do echo "warm_open_s=$(appopen_until_ux)"; osascript -e 'tell application "Wizard" to quit' 2>/dev/null; sleep 2; done

echo "== 3. cold open (WizardOS stopped)"
for n in 1 2; do
  hostcmd stop
  for i in $(seq 1 120); do sleep 0.5; grep -q '"stopped"' "$AS/host-status.json" && break; done
  grep state "$AS/host-status.json"; sleep 1
  echo "cold_open_s=$(appopen_until_ux)"; grep -o '"bootSeconds" : [0-9.]*' "$AS/host-status.json"
  snap cold-open-$n; sleep 1
  osascript -e 'tell application "Wizard" to quit' 2>/dev/null; sleep 2
done
sleep 60; echo "== memory after cold boot + 60 s"; mem

echo "== 4. chats, installed apps and files after quit/reopen and two WizardOS restarts"
AFTER=$(snapshot_data); echo "$AFTER"
[ "$BEFORE" = "$AFTER" ] && echo "PERSIST_OK" || echo "PERSIST_DIFF"
curl -s http://127.0.0.1:48030/api/state | python3 -c "import json,sys;d=json.load(sys.stdin);print('name',d['name'],'done',d['done'],'brain',(d['brain'] or {}).get('label'))"
echo "== log"; tail -12 "$AS/logs/host.log"
