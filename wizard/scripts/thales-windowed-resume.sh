#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Resume windowed pipeline after a successful runtime stage: verify runtime -> app -> DMG.
set -uo pipefail
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
bash ~/wd-heal.sh >/dev/null 2>&1 || true
source "$D/env.sh"
export TMPDIR="$D/tmp"
cd "$D/try-omarchy" || exit 1
rm -rf "$D"/tmp/omarchy-qemu-source-build.*
git checkout -q -- macos/build-qemu-gpu-runtime.sh
python3 "$D/scripts/apply-wizard-app-patch.py" "$D/try-omarchy" | tail -1
grep -c "wizard-cocoa-edit: OK" "$D/build-runtime-windowed.log"
Q=macos/.build/qemu-gpu-runtime/bin/qemu-system-aarch64
echo "quit-string=$(strings -a $Q | grep -c 'quit Wizard') autosave=$(strings -a $Q | grep -c WizardMainWindow) stamp=$(stat -f %Sm $Q)"
echo "== app $(date)"
macos/build-app.sh --configuration production --sign-identity - --guest-dir "$D/guest-wizard" > "$D/build-app-windowed.log" 2>&1 || { echo APP_FAILED; tail -30 "$D/build-app-windowed.log"; exit 1; }
echo "== dmg $(date)"
/bin/bash "$D/scripts/thales-dmg-headless.sh" 2>&1 | tail -4
echo WINDOWED_PIPELINE_OK
