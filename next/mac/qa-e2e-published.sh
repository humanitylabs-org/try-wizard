#!/bin/bash
# End-to-end acceptance on Thales from the PUBLISHED artifacts: install the DMG from the private
# download page, wipe Wizard OS + app prefs, choose "On this Mac", and let the app pull Wizard OS
# from the app's configured OS feed. Set WIZARD_QA_DOWNLOAD_BASE to the published release directory.
set -u
: "${WIZARD_QA_DOWNLOAD_BASE:?Set WIZARD_QA_DOWNLOAD_BASE to the published release directory URL}"
B=${WIZARD_QA_DOWNLOAD_BASE%/}
AS="$HOME/Library/Application Support/Wizard"
APP="$HOME/Applications/WizardNext/Wizard.app"
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
W="$WIZARD_WORK_ROOT/Projects/wizard-desktop/wizard-mac"
T=/tmp/wizard-e2e; rm -rf $T; mkdir -p $T

echo "== stop running Wizard"
pkill -x Wizard; pkill -TERM -f "Wizard Host.app/Contents/MacOS"
for i in $(seq 1 30); do pgrep -f "Wizard Host.app/Contents/MacOS" >/dev/null || break; sleep 1; done

echo "== wipe Wizard OS, logs, prefs (keep the old QEMU build's VM dir)"
rm -rf "$AS/os" "$AS/logs" "$AS/host-status.json" "$AS/downloads"
defaults delete org.humanitylabs.wizard.mvp >/dev/null 2>&1 || true
defaults delete org.humanitylabs.wizard.mvp.host >/dev/null 2>&1 || true

echo "== download + verify DMG from the private page"
curl -sSf -o $T/Wizard.dmg $B/Wizard-0.2.0.dmg
want=$(curl -sSf $B/Wizard-0.2.0.dmg.sha256 | cut -d' ' -f1)
got=$(shasum -a 256 $T/Wizard.dmg | cut -d' ' -f1)
[ "$want" = "$got" ] && echo "dmg sha256 ok" || { echo "DMG SHA MISMATCH"; exit 1; }

echo "== install from DMG"
MNT=$(hdiutil attach -nobrowse -readonly $T/Wizard.dmg | awk -F'\t' '/\/Volumes\//{print $NF}')
rm -rf "$APP"; mkdir -p "$(dirname "$APP")"; ditto "$MNT/Wizard.app" "$APP"; hdiutil detach -quiet "$MNT"
codesign --verify --deep --strict "$APP" && echo "codesign ok"
defaults write org.humanitylabs.wizard.mvp QAHooks -bool true   # QA-only control channel; feed URL left at its default

echo "== launch + choose On this Mac"
t0=$(python3 -c 'import time;print(time.time())')
open "$APP"; sleep 2
cd $W/mac; bash qa.sh choose-this-mac >/dev/null 2>&1
while python3 -c "import time,sys;sys.exit(0 if time.time()-$t0<240 else 1)"; do
  sleep 1; /tmp/wizard-mvp-qa-post state 2>/dev/null; sleep 0.1
  python3 -c "import json,sys;d=json.load(open('/tmp/wizard-mvp-qa-state.json'));sys.exit(0 if d['overlayHidden'] or d['title'].startswith(('Can','Wizard OS didn','Couldn')) else 1)" 2>/dev/null && break
done
python3 -c "import json,time;d=json.load(open('/tmp/wizard-mvp-qa-state.json'));print('first_run_to_window_s=%.1f'%(time.time()-$t0), '|', d['title'], '|', d['url'])"
grep -E "downloaded|verified|unpack|ready in|feed" "$AS/logs/host.log" "$AS/logs/app.log" 2>/dev/null | tail -6
cat "$AS/os/manifest.json" 2>/dev/null | python3 -c "import json,sys;print('installed Wizard OS', json.load(sys.stdin)['version'])"
curl -s http://127.0.0.1:48030/api/state; echo
bash qa.sh "snapshot /tmp/wq-e2e.png" >/dev/null 2>&1; sleep 2; ls -la /tmp/wq-e2e.png

echo "== onboarding immediately after boot"
B=http://127.0.0.1:48030
curl -s -XPOST $B/api/name -H content-type:application/json -d '{"name":"Merlin"}' >/dev/null
curl -s -m 60 -XPOST $B/api/brain -H content-type:application/json -d '{"kind":"free"}' | python3 -c "import json,sys;d=json.load(sys.stdin);print('brain:',(d.get('brain') or {}).get('label'),d.get('error',''))"
curl -s -m 200 -XPOST $B/api/verify | python3 -c "import json,sys;d=json.load(sys.stdin);print('verify:',d.get('reply') or d.get('error'))"
