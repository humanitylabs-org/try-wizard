#!/bin/bash
# Build Wizard.app (front end) with Wizard Host.app (back-end runner) embedded as a login item.
# Runs on Thales. Output: dist/Wizard.app, dist/Wizard-<ver>.dmg
set -euo pipefail
VER=${VER:-0.3.0}
BUILD=${BUILD:-1}
cd "$(dirname "$0")"
SRC=$PWD
OUT=$SRC/dist
rm -rf "$OUT/Wizard.app" "$OUT/obj"; mkdir -p "$OUT/obj"

TARGET="arm64-apple-macos14.0"
SWIFTC=(xcrun swiftc -O -target "$TARGET" -swift-version 5)

APP=$OUT/Wizard.app
HOST=$APP/Contents/Library/LoginItems/"Wizard Host.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$HOST/Contents/MacOS" "$HOST/Contents/Resources"

"${SWIFTC[@]}" Shared/Shared.swift Host/main.swift -framework Virtualization -framework AppKit -o "$HOST/Contents/MacOS/Wizard Host"
"${SWIFTC[@]}" Shared/Shared.swift App/WizardKeys.swift App/main.swift -framework WebKit -framework AppKit -framework ServiceManagement -framework Carbon -o "$APP/Contents/MacOS/Wizard"

plist() { # $1 path $2 name $3 bundle id $4 exec $5 extra
cat > "$1" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>$2</string>
<key>CFBundleDisplayName</key><string>$2</string>
<key>CFBundleIdentifier</key><string>$3</string>
<key>CFBundleExecutable</key><string>$4</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>$VER</string>
<key>CFBundleVersion</key><string>$BUILD</string>
<key>CFBundleIconFile</key><string>Wizard</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/><key>NSAllowsArbitraryLoads</key><true/></dict>
$5
</dict></plist>
EOF
}
plist "$APP/Contents/Info.plist" "Wizard" org.humanitylabs.wizard Wizard \
  '<key>LSApplicationCategoryType</key><string>public.app-category.productivity</string><key>NSMicrophoneUsageDescription</key><string>Wizard uses the microphone for voice messages.</string><key>NSCameraUsageDescription</key><string>Wizard uses the camera when you share a photo.</string>'
plist "$HOST/Contents/Info.plist" "Wizard Host" org.humanitylabs.wizard.host "Wizard Host" '<key>LSUIElement</key><true/>'

if [[ -f assets/Wizard.icns ]]; then
  cp assets/Wizard.icns "$APP/Contents/Resources/Wizard.icns"
  cp assets/Wizard.icns "$HOST/Contents/Resources/Wizard.icns"
fi

cat > "$OUT/obj/host.entitlements" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.apple.security.virtualization</key><true/></dict></plist>
EOF
codesign --force --sign - --options runtime --entitlements "$OUT/obj/host.entitlements" "$HOST"
codesign --force --sign - --options runtime "$APP"
codesign --verify --deep --strict "$APP"
du -sh "$APP"

if [[ "${DMG:-1}" == 1 ]]; then
  STAGE=$OUT/obj/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
  ditto "$APP" "$STAGE/Wizard.app"; ln -s /Applications "$STAGE/Applications"
  rm -f "$OUT/Wizard-$VER.dmg"
  hdiutil create -quiet -volname "Wizard" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$OUT/Wizard-$VER.dmg"
  shasum -a 256 "$OUT/Wizard-$VER.dmg"; ls -la "$OUT/Wizard-$VER.dmg"
fi
echo BUILD_OK
