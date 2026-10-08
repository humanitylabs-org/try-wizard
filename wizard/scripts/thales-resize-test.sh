#!/bin/bash
# Free-resize check: does the guest display follow the window shape (no 16:9 lock)?
# 1) current window vs guest mode  2) relaunch with a phone-shaped saved frame and re-check.
D=/Volumes/ThalesMedia/Projects/wizard-desktop
mon() { python3 -c 'import json;print(json.dumps({"cmd":"sudo -u wizard XDG_RUNTIME_DIR=/run/user/$(id -u wizard) HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/$(id -u wizard)/hypr | head -1) hyprctl monitors | sed -n 2p","timeout":20}))' | curl -s -m 30 -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:18930/api/dev/exec; echo; }
echo "== now"; swift /tmp/wd-win.swift 2>&1 | head -1; mon
echo "== phone-shaped"
H=$(pgrep -f "Wizard.app/Contents/MacOS/omarchy-vm-helper" | head -1)
kill -TERM "$H"; for i in $(seq 1 60); do pgrep -f "runtime/bin/Wizard" >/dev/null || break; sleep 1; done
defaults write Wizard "NSWindow Frame WizardWindow" "700 120 520 860 0 0 1920 1055 "
defaults read Wizard "NSWindow Frame WizardWindow"
bash "$D/scripts/thales-launch.sh"
for i in $(seq 1 40); do curl -s -o /dev/null -m 2 http://127.0.0.1:18930/api/state && break; sleep 3; done
sleep 12
swift /tmp/wd-win.swift 2>&1 | head -1; mon
rm -f /tmp/wd-guest.jpg; bash "$D/scripts/thales-guest-shot.sh" 2>&1 | tail -2
