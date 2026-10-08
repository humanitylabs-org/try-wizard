#!/bin/bash
# Headless DMG: Wizard.app + Applications link, compressed, ad-hoc signed. No Finder scripting.
set -euo pipefail
D=/Volumes/ThalesMedia/Projects/wizard-desktop
APP="$D/try-omarchy/dist/release.noindex/Wizard.app"
OUT="$D/try-omarchy/dist/Wizard.dmg"
STAGE="$D/tmp/dmg-stage"
export TMPDIR="$D/tmp"
rm -rf "$STAGE" "$OUT"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/Wizard.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname Wizard -srcfolder "$STAGE" -fs APFS -format UDZO -imagekey zlib-level=6 "$OUT"
codesign --force --sign - --identifier com.aiwizards.desktop.disk-image "$OUT"
codesign --verify --strict "$OUT" && echo dmg_signed_ok
hdiutil verify "$OUT" >/dev/null && echo dmg_verify_ok
rm -rf "$STAGE"
ls -la "$OUT"
shasum -a 256 "$OUT"
