#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Run on Thales: remaster guest at the current SIZE_MIB, rebuild app from pristine sources.
set -uo pipefail
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
/bin/bash "$D/scripts/thales-remaster.sh"
grep -q "REMASTER_OK" "$D/build-remaster.log" || { echo "REMASTER FAILED"; tail -20 "$D/build-remaster.log"; exit 1; }
cd "$D/try-omarchy" && git checkout -- macos
/bin/bash "$D/scripts/thales-build-app.sh"
grep -E "WIZARD_PATCH_OK|build_rc" "$D/build-app-wizard.log"
