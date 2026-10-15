#!/bin/bash
# Build Wizard.app (front end) with Wizard Host.app (back-end runner) embedded as a login item.
# Runs on Thales. Output: dist/Wizard.app, dist/Wizard-<ver>.dmg
set -euo pipefail
VER=${VER:-0.7.0}
BUILD=${BUILD:?Set BUILD to a new monotonic positive release build number}
[[ "$BUILD" =~ ^[1-9][0-9]*$ ]] || { printf 'Invalid BUILD: positive decimal required\n' >&2; exit 2; }
cd "$(dirname "$0")"
SRC=$PWD
SPARKLE_DIR=${SPARKLE_DIR:?Set SPARKLE_DIR to verified Sparkle 2.10.0 distribution on Thales}
SPARKLE_PUBLIC_KEY=${SPARKLE_PUBLIC_KEY:?Set the public Ed25519 key; private key must stay on signer}
SPARKLE_FEED=${SPARKLE_FEED:-https://downloads.aiwizards.com/mac/appcast.xml}
SIGN_IDENTITY=${SIGN_IDENTITY:--}
RELEASE_ID=${RELEASE_ID:-$(git rev-parse HEAD)}
OUT=$SRC/dist
rm -rf "$OUT/Wizard.app" "$OUT/obj"; mkdir -p "$OUT/obj"

TARGET="arm64-apple-macos14.0"
SWIFTC=(xcrun swiftc -O -target "$TARGET" -swift-version 5)

APP=$OUT/Wizard.app
HOST=$APP/Contents/Library/LoginItems/"Wizard Host.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$HOST/Contents/MacOS" "$HOST/Contents/Resources"

mkdir -p "$APP/Contents/Frameworks"
ditto "$SPARKLE_DIR/Sparkle.framework" "$APP/Contents/Frameworks/Sparkle.framework"
"${SWIFTC[@]}" Shared/Shared.swift Shared/Brand.swift Shared/UpdateContract.swift Shared/GuestPatchCommand.swift Shared/HostTermination.swift Host/main.swift -framework Virtualization -framework AppKit -o "$HOST/Contents/MacOS/Wizard Host"
"${SWIFTC[@]}" Shared/Shared.swift Shared/Brand.swift Shared/UpdateContract.swift App/WizardKeys.swift App/MeetingCapture.swift App/MeetingUI.swift App/WizardGuestActivation.swift App/WizardUpdater.swift App/main.swift -F "$SPARKLE_DIR" -framework Sparkle -Xlinker -rpath -Xlinker @executable_path/../Frameworks -framework WebKit -framework AppKit -framework ServiceManagement -framework Carbon -framework AVFoundation -framework CoreAudio -framework CoreMedia -framework ScreenCaptureKit -framework ApplicationServices -o "$APP/Contents/MacOS/Wizard"


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
plist "$APP/Contents/Info.plist" "Wizard MVP" org.humanitylabs.wizard.mvp Wizard \
  '<key>LSApplicationCategoryType</key><string>public.app-category.productivity</string><key>NSMicrophoneUsageDescription</key><string>Wizard uses the microphone for voice messages, dictation and recording your side of meetings.</string><key>NSAudioCaptureUsageDescription</key><string>Wizard records the other side of your calls (the audio your Mac plays) when you start a meeting recording.</string><key>NSScreenCaptureUsageDescription</key><string>Wizard can use screen audio to record calls if direct call audio is unavailable.</string><key>NSCameraUsageDescription</key><string>Wizard uses the camera when you share a photo.</string>'
plist "$HOST/Contents/Info.plist" "Wizard Host" org.humanitylabs.wizard.mvp.host "Wizard Host" '<key>LSUIElement</key><true/>'

# Public metadata only. A private GitHub feed fails visibly; no embedded login/token.
export APP SPARKLE_PUBLIC_KEY SPARKLE_FEED RELEASE_ID BUILD
/usr/bin/python3 - <<'PY'
import hashlib,json,os,pathlib,plistlib,struct
a=pathlib.Path(os.environ['APP']); p=a/'Contents/Info.plist'
import urllib.parse
feed=urllib.parse.urlsplit(os.environ['SPARKLE_FEED'])
assert feed.scheme=='https' or (feed.scheme=='http' and feed.hostname in ('127.0.0.1','::1','localhost')), 'Only HTTPS distribution or loopback developer feeds are allowed'
d=plistlib.loads(p.read_bytes()); d.update(SUFeedURL=os.environ['SPARKLE_FEED'],SUPublicEDKey=os.environ['SPARKLE_PUBLIC_KEY'],SUEnableAutomaticChecks=True,SUAutomaticallyUpdate=False,SUSendProfileInfo=False,SUVerifyUpdateBeforeExtraction=True,SURequireSignedFeed=True,SUUpdateCheckInterval=3600)
p.write_bytes(plistlib.dumps(d))
files=['Contents/MacOS/Wizard','Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host']
guest=os.environ.get('GUEST_UPDATE_PAYLOAD')
if guest:
 import shutil
 shutil.copytree(guest,a/'Contents/Resources/GuestUpdate',symlinks=False)
 files += [str(p.relative_to(a)) for p in (a/'Contents/Resources/GuestUpdate').rglob('*') if p.is_file()]
def digest(f):
 if '/Contents/MacOS/' in '/'+f:
  data=(a/f).read_bytes()
  assert struct.unpack_from('<I',data)[0]==0xfeedfacf
  at=32
  for _ in range(struct.unpack_from('<I',data,16)[0]):
   cmd,size=struct.unpack_from('<II',data,at)
   if cmd==0x19:
    for i in range(struct.unpack_from('<I',data,at+64)[0]):
     s=at+72+i*80
     if data[s:s+16].split(b'\0')[0]==b'__text':
      length=struct.unpack_from('<Q',data,s+40)[0]; start=struct.unpack_from('<I',data,s+48)[0]
      return hashlib.sha256(data[start:start+length]).hexdigest()
   at+=size
  raise RuntimeError('Missing native text section')
 h=hashlib.sha256()
 with (a/f).open('rb') as stream:
  while True:
   chunk=stream.read(1024*1024)
   if not chunk:break
   h.update(chunk)
 return h.hexdigest()
r=dict(schema=1,releaseID=os.environ['RELEASE_ID'],build=os.environ['BUILD'],arch='arm64',minimumOS='14.0',hostProtocol=1,minimumPeer=1,files={f:digest(f) for f in files},guestPatch='mac-stack-v1' if guest else None)
(a/'Contents/Resources/wizard-release.json').write_text(json.dumps(r,sort_keys=True)+'\n')
PY

# "Bring My Hermes into Wizard": backs up the Mac's Hermes and posts it to Wizard OS's front door (127.0.0.1:48030).
mkdir -p "$APP/Contents/Resources/bring-hermes"
install -m 755 bring-hermes/wizard-bring-hermes "$APP/Contents/Resources/bring-hermes/wizard-bring-hermes"

python3 assets/build-icon.py assets/brand "$OUT/obj/Wizard.icns"
for bundle in "$APP" "$HOST"; do
  cp "$OUT/obj/Wizard.icns" "$bundle/Contents/Resources/Wizard.icns"
  cp assets/brand/wizard-mark-{purple,white}.png "$bundle/Contents/Resources/"
  cp assets/brand/provenance.json "$bundle/Contents/Resources/WizardBrandProvenance.json"
done


cat > "$OUT/obj/host.entitlements" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.apple.security.virtualization</key><true/></dict></plist>
EOF
codesign --force --sign "$SIGN_IDENTITY" --options runtime --entitlements "$OUT/obj/host.entitlements" "$HOST"
cat > "$OUT/obj/app.entitlements" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.apple.security.device.audio-input</key><true/><key>com.apple.security.device.camera</key><true/></dict></plist>
EOF
if [[ "$SIGN_IDENTITY" == - ]]; then
  /usr/libexec/PlistBuddy -c 'Add :com.apple.security.cs.disable-library-validation bool true' "$OUT/obj/app.entitlements"
fi
# Explicit inside-out signing: retain no implicit --deep signing repair.
FRAMEWORK="$APP/Contents/Frameworks/Sparkle.framework"
for x in "$FRAMEWORK"/Versions/B/XPCServices/*.xpc "$FRAMEWORK"/Versions/B/Updater.app "$FRAMEWORK"/Versions/B/Autoupdate; do
  [[ ! -e "$x" ]] || codesign --force --sign "$SIGN_IDENTITY" --options runtime "$x"
done
codesign --force --sign "$SIGN_IDENTITY" --options runtime "$FRAMEWORK"
codesign --force --sign "$SIGN_IDENTITY" --options runtime --entitlements "$OUT/obj/app.entitlements" "$APP"
codesign --verify --deep --strict "$APP"
du -sh "$APP"

if [[ "${DMG:-1}" == 1 ]]; then
  STAGE=$OUT/obj/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
  ditto "$APP" "$STAGE/Wizard MVP.app"; ln -s /Applications "$STAGE/Applications"
  rm -f "$OUT/Wizard-$VER.dmg"
  hdiutil create -quiet -volname "Wizard" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$OUT/Wizard-$VER.dmg"
  shasum -a 256 "$OUT/Wizard-$VER.dmg"; ls -la "$OUT/Wizard-$VER.dmg"
fi
echo BUILD_OK
