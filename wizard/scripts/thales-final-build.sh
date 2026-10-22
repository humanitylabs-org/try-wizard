#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Full pipeline on Thales: remaster guest -> build app -> headless DMG.
set -uo pipefail
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
pkill -f "Wizard.app/Contents/MacOS/omarchy-vm-helper" || true
sleep 3
/bin/bash "$D/scripts/thales-rebuild-all.sh" || { echo PIPELINE_FAILED_BUILD; exit 1; }
grep -q "build_rc=0" "$D/build-app-wizard.log" || { echo PIPELINE_FAILED_APP; exit 1; }
/bin/bash "$D/scripts/thales-dmg-headless.sh" || { echo PIPELINE_FAILED_DMG; exit 1; }
echo PIPELINE_OK
