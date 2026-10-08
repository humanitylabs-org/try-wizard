#!/bin/bash
# Fresh-install QA on Thales: wipe Wizard OS, open Wizard.app, choose "On this Mac", time until the UX is on screen.
W=/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-mac
AS="$HOME/Library/Application Support/Wizard"
pkill -x Wizard; pkill -f "Wizard Host.app/Contents/MacOS"; sleep 3
rm -rf "$AS/os" "$AS/logs" "$AS/host-status.json" "$AS/os-staging"
defaults delete org.humanitylabs.wizard backends 2>/dev/null
defaults write org.humanitylabs.wizard QAHooks -bool true
open ~/Applications/WizardNext/Wizard.app; sleep 2
cd $W/mac
T0=$(python3 -c 'import time;print(time.time())')
bash qa.sh choose-this-mac
for i in $(seq 1 ${STEPS:-60}); do
  sleep 2; bash qa.sh state
  T=$(python3 -c 'import json;d=json.load(open("/tmp/wizard-qa-state.json"));print(d["overlayHidden"],d["title"],"|",d["url"])')
  echo "$((i*2))s $T"
  case "$T" in True*|*"didn"*|*"Can"*) break;; esac
done
python3 -c "import json,time;d=json.load(open('/tmp/wizard-qa-state.json'));print('ux-visible-after %.1fs'%(d['loadedAt']-$T0) if d['loadedAt'] else 'not-loaded')"
grep -E "ready|starting|fail|error" "$AS/logs/host.log"
grep -aE "FAILED|DEPEND" "$AS/logs/console.log" | tail -10
