#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Windowed rebuild on Thales: patch fork -> rebuild QEMU runtime (Cocoa edit) -> app -> headless DMG.
# Guest image is reused unchanged, so existing Wizards keep their disk.
set -uo pipefail
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
bash ~/wd-heal.sh >/dev/null 2>&1 || true
source "$D/env.sh"
mkdir -p "$D/tmp"
export TMPDIR="$D/tmp"
cd "$D/try-omarchy" || { echo NO_FORK; exit 1; }
python3 "$D/scripts/apply-wizard-app-patch.py" "$D/try-omarchy" || { echo PATCH_FAILED; exit 1; }
echo "== runtime $(date)"
macos/build-qemu-gpu-runtime.sh > "$D/build-runtime-windowed.log" 2>&1 || { echo RUNTIME_FAILED; tail -30 "$D/build-runtime-windowed.log"; exit 1; }
grep -c "wizard-cocoa-edit: OK" "$D/build-runtime-windowed.log"
strings -a macos/.build/qemu-gpu-runtime/bin/qemu-system-aarch64 | grep -c "quit Wizard"
echo "== app $(date)"
macos/build-app.sh --configuration production --sign-identity - --guest-dir "$D/guest-wizard" > "$D/build-app-windowed.log" 2>&1 || { echo APP_FAILED; tail -30 "$D/build-app-windowed.log"; exit 1; }
echo "== dmg $(date)"
/bin/bash "$D/scripts/thales-dmg-headless.sh" 2>&1 | tail -4 || { echo DMG_FAILED; exit 1; }
echo WINDOWED_PIPELINE_OK
