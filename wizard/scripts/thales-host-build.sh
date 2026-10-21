#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Rebuild host side only (QEMU runtime with Cocoa edit -> app -> DMG -> small app-update tarball).
# Guest image is reused unchanged, so existing Wizards keep their disk.
set -uo pipefail
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
VER=${1:?version}
bash ~/wd-heal.sh >/dev/null 2>&1 || true
source "$D/env.sh"
mkdir -p "$D/tmp"
export TMPDIR="$D/tmp"
cd "$D/try-omarchy" || { echo NO_FORK; exit 1; }
python3 "$D/scripts/apply-wizard-app-patch.py" "$D/try-omarchy" || { echo PATCH_FAILED; exit 1; }
echo "== runtime $(date)"
macos/build-qemu-gpu-runtime.sh > "$D/build-runtime-$VER.log" 2>&1 || { echo RUNTIME_FAILED; tail -30 "$D/build-runtime-$VER.log"; exit 1; }
grep -h "wizard-cocoa-edit: OK" "$D/build-runtime-$VER.log" | head -1
B=macos/.build/qemu-gpu-runtime/bin/qemu-system-aarch64
echo "quit-string=$(strings -a $B | grep -c 'quit Wizard') autosave=$(strings -a $B | grep -c '^WizardWindow$')"
echo "== app $(date)"
macos/build-app.sh --configuration production --sign-identity - --guest-dir "$D/guest-wizard" > "$D/build-app-$VER.log" 2>&1 || { echo APP_FAILED; tail -30 "$D/build-app-$VER.log"; exit 1; }
echo "== dmg $(date)"
/bin/bash "$D/scripts/thales-dmg-headless.sh" 2>&1 | tail -3 || { echo DMG_FAILED; exit 1; }
cp dist/Wizard.dmg "dist/Wizard-$VER.dmg"
echo "== app-only update $(date)"
APP=dist/release.noindex/Wizard.app
rm -f "dist/Wizard-$VER-app.tar.gz"
tar -C dist/release.noindex --exclude 'Wizard.app/Contents/Resources/guest' -czf "dist/Wizard-$VER-app.tar.gz" Wizard.app
ls -la "dist/Wizard-$VER-app.tar.gz" "dist/Wizard-$VER.dmg"
shasum -a 256 "dist/Wizard-$VER-app.tar.gz" "dist/Wizard-$VER.dmg"
du -sh "$APP/Contents/Resources/guest"
echo HOST_PIPELINE_OK
