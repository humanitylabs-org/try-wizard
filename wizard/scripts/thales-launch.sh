#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Launch Wizard.app helper in the GUI session with stderr captured. Part 2 of the boot test.
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
H="$HOME/Applications/Wizard.app/Contents/MacOS/omarchy-vm-helper"
mkdir -p "$D/qa"
: > "$D/qa/helper-stderr.log"
sudo -n launchctl asuser "$(id -u)" sudo -u "$(id -un)" /bin/bash -c "'$H' --run-qemu >>'$D/qa/helper-stderr.log' 2>&1 &"
echo "launched"
