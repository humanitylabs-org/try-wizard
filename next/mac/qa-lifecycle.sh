#!/bin/bash
# Lifecycle QA on Thales for the split Wizard app. Assumes Wizard OS is installed and onboarded.
W=/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-mac
AS="$HOME/Library/Application Support/Wizard"
cd $W/mac
bash qa.sh state >/dev/null 2>&1  # compiles /tmp/wizard-qa-post
now() { python3 -c 'import time;print(time.time())'; }
# Wizard's VM = the Virtualization XPC process started most recently (Colima's is days old).
vmproc() { pgrep -n -f "com.apple.Virtualization.VirtualMachine"; }
appopen_until_ux() { # prints seconds from `open` until the UX page finished loading in the window
  local t0=$(now); open ~/Applications/WizardNext/Wizard.app
  rm -f /tmp/wizard-qa-state.json
  while python3 -c "import time,sys;sys.exit(0 if time.time()-$t0<60 else 1)"; do
    sleep 0.1; /tmp/wizard-qa-post state 2>/dev/null; sleep 0.05
    python3 -c "import json,sys;d=json.load(open('/tmp/wizard-qa-state.json'));sys.exit(0 if (d['overlayHidden'] and d['loadedAt']>$t0) or d['title'].startswith(('Can','Wizard OS didn')) else 1)" 2>/dev/null && break
  done
  python3 -c "import json;d=json.load(open('/tmp/wizard-qa-state.json'));print('%.2f'%(d['loadedAt']-$t0) if d['overlayHidden'] and d['loadedAt'] else 'FAIL '+d['title']+' / '+d['subtitle'])"
}
mem() {
  local p=$(vmproc); local h=$(pgrep -f "Wizard Host.app/Contents/MacOS"); local a=$(pgrep -x Wizard)
  echo "vm_process_rss_mb=$(( $(ps -o rss= -p ${p:-1}) / 1024 )) host_rss_mb=$(( $(ps -o rss= -p ${h:-1} 2>/dev/null || echo 0) / 1024 )) app_rss_mb=$(( $(ps -o rss= -p ${a:-1} 2>/dev/null || echo 0) / 1024 ))"
  [[ -n "$p" ]] && footprint "$p" 2>/dev/null | grep -E "Footprint|phys_footprint" | head -2
}

echo "== 1. window closed -> Wizard OS keeps running"
pkill -x Wizard; sleep 2
pgrep -x Wizard >/dev/null && echo "app still running" || echo "app quit"
cat "$AS/host-status.json" | grep state
curl -s -m 3 http://127.0.0.1:47830/healthz && echo " <- back end still answering with window closed"
mem

echo "== 2. warm open (back end already running)"
for n in 1 2 3; do echo "warm_open_s=$(appopen_until_ux)"; pkill -x Wizard; sleep 1.5; done

echo "== 3. cold open (Wizard OS stopped)"
for n in 1 2; do
  bash -c 'cat > /tmp/hc.swift <<EOF
import Foundation
DistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.host.command"), object: "stop", userInfo: nil, deliverImmediately: true)
RunLoop.main.run(until: Date().addingTimeInterval(0.3))
EOF
[[ -x /tmp/hc ]] || xcrun swiftc -O /tmp/hc.swift -o /tmp/hc 2>/dev/null; /tmp/hc'
  for i in $(seq 1 60); do sleep 0.5; grep -q '"stopped"' "$AS/host-status.json" && break; done
  grep state "$AS/host-status.json"; sleep 1
  echo "cold_open_s=$(appopen_until_ux)"; grep -o '"bootSeconds" : [0-9.]*' "$AS/host-status.json"
  pkill -x Wizard; sleep 1.5
done
mem

echo "== 4. data persists across Wizard OS restarts"
B=http://127.0.0.1:47830
curl -s $B/api/state | python3 -c "import json,sys;d=json.load(sys.stdin);print('name',d['name'],'done',d['done'],'brain',(d['brain'] or {}).get('label'))"
echo "== log"
tail -12 "$AS/logs/host.log"
