#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Final acceptance for 0.1.2: fresh default size, guest follows window, narrow frame clamps to 520.
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
defaults delete Wizard "NSWindow Frame WizardWindow" 2>/dev/null
defaults delete Wizard "NSWindow Frame WizardMainWindow" 2>/dev/null
bash "$D/scripts/thales-quick-update-test.sh" 2>&1 | grep -E "installed|codesign|guest up"
sleep 10
echo "== fresh open"; swift /tmp/wd-win.swift 2>&1 | head -2
bash "$D/scripts/thales-display-diag.sh" | tail -1
echo "== saved 400-wide frame"
H=$(pgrep -f "Wizard.app/Contents/MacOS/omarchy-vm-helper" | head -1); kill -TERM "$H"
for i in $(seq 1 60); do pgrep -f "runtime/bin/Wizard" >/dev/null || break; sleep 1; done
defaults write Wizard "NSWindow Frame WizardWindow" "760 120 400 860 0 0 1920 1055 "
bash "$D/scripts/thales-launch.sh" >/dev/null
for i in $(seq 1 40); do curl -s -o /dev/null -m 2 http://127.0.0.1:18930/api/state && break; sleep 3; done
sleep 12
swift /tmp/wd-win.swift 2>&1 | head -1
bash "$D/scripts/thales-display-diag.sh" | tail -1
