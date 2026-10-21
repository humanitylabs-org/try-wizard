#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Fresh install of Wizard.app on Thales + dev port forwards. Part 1 of the boot test.
set -uo pipefail
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
APP_SRC="$D/try-omarchy/dist/release.noindex/Wizard.app"
APP="$HOME/Applications/Wizard.app"
pkill -f "Wizard.app/Contents/MacOS/omarchy-vm-helper"
sleep 3
rm -rf "$HOME/Library/Application Support/Wizard"
rm -rf "$APP"
mkdir -p "$HOME/Applications"
ditto "$APP_SRC" "$APP"
codesign --verify --deep --strict "$APP" && echo "codesign ok"
python3 "$D/scripts/set-dev-forwards.py"
echo "install done"
