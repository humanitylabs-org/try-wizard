#!/bin/bash
# Unsigned, app-only fixture build. No Host, VM, DMG, release or production defaults.
# On Thales, under the shared worker lock:
# SPARKLE_DIR=<verified Sparkle 2.10.0 dir> bash tools/build-workspaces-qa.sh <new-output-directory>
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(uname -s) == Darwin ]] || { printf 'macOS required\n' >&2; exit 1; }
: "${SPARKLE_DIR:?Use the verified Sparkle 2.10.0 distribution}"
OUT=${1:?new-output-directory required}
[[ ! -e "$OUT" ]] || { printf 'Refusing existing output\n' >&2; exit 1; }
mkdir -p "$OUT/Wizard Switcher QA.app/Contents/"{MacOS,Frameworks,Resources}
APP="$OUT/Wizard Switcher QA.app"
ditto "$SPARKLE_DIR/Sparkle.framework" "$APP/Contents/Frameworks/Sparkle.framework"
# WizardBrand.image() deliberately traps if either required designer asset is
# missing. App-only QA still constructs the branded overlay and status menu.
cp assets/brand/wizard-mark-{purple,white}.png "$APP/Contents/Resources/"
cp assets/brand/provenance.json "$APP/Contents/Resources/WizardBrandProvenance.json"
set -x
xcrun swiftc -O -target arm64-apple-macos14.0 -swift-version 5 \
  Shared/Shared.swift Shared/DiskIdentity.swift Shared/Brand.swift Shared/UpdateContract.swift \
  Shared/BackupContract.swift Shared/WorkspaceStore.swift App/WizardBackup.swift App/WizardKeys.swift \
  App/MeetingCapture.swift App/MeetingUI.swift App/WizardGuestActivation.swift App/WizardUpdater.swift \
  App/WorkspacePages.swift App/main.swift -F "$SPARKLE_DIR" -framework Sparkle \
  -Xlinker -rpath -Xlinker @executable_path/../Frameworks -framework Security \
  -framework UniformTypeIdentifiers -framework CryptoKit -framework WebKit -framework AppKit \
  -framework ServiceManagement -framework Carbon -framework AVFoundation -framework CoreAudio \
  -framework CoreMedia -framework ScreenCaptureKit -framework ApplicationServices \
  -o "$APP/Contents/MacOS/Wizard"
set +x
python3 - "$APP" <<'PY'
import pathlib, plistlib, sys, uuid
app = pathlib.Path(sys.argv[1])
(app/'Contents/Info.plist').write_bytes(plistlib.dumps({
 'CFBundleIdentifier':'org.humanitylabs.wizard.switcherqa.' + uuid.uuid4().hex,
 'CFBundleName':'Wizard Switcher QA', 'CFBundleExecutable':'Wizard',
 'CFBundlePackageType':'APPL', 'CFBundleVersion':'1', 'CFBundleShortVersionString':'0.0.0',
 'LSMinimumSystemVersion':'14.0', 'NSHighResolutionCapable':True,
 'NSAppTransportSecurity': {'NSAllowsArbitraryLoads':True, 'NSAllowsLocalNetworking':True}
}))
PY
printf 'UNSIGNED_SWITCHER_QA_BUILD_OK %s\n' "$APP"
