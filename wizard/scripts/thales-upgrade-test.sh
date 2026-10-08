#!/bin/bash
# Upgrade-in-place test: keep existing Wizard state, install new DMG over the app, launch, verify windowed.
set -uo pipefail
D=/Volumes/ThalesMedia/Projects/wizard-desktop
DMG="$D/try-omarchy/dist/Wizard.dmg"
pkill -f "Wizard.app/Contents/MacOS/omarchy-vm-helper" || true
for i in $(seq 1 20); do pgrep -f "runtime/bin/Wizard" >/dev/null || break; sleep 1; done
echo "state kept: $(du -sh "$HOME/Library/Application Support/Wizard" | cut -f1)"
echo "fullscreen pref before: $(defaults read com.aiwizards.desktop fullscreenPreferences 2>&1 | head -1)"
M=$(hdiutil attach -nobrowse -readonly "$DMG" | awk -F'\t' '/\/Volumes\//{print $NF}' | tail -1)
rm -rf "$HOME/Applications/Wizard.app"
ditto "$M/Wizard.app" "$HOME/Applications/Wizard.app"
hdiutil detach -quiet "$M"
codesign --verify --deep --strict "$HOME/Applications/Wizard.app" && echo "codesign ok"
python3 "$D/scripts/set-dev-forwards.py" >/dev/null 2>&1 && echo "dev forwards set"
bash "$D/scripts/thales-launch.sh"
for i in $(seq 1 60); do
  c=$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:18930/api/state)
  [ "$c" = 200 ] && { echo "guest up after $((i*5))s"; break; }
  sleep 5
done
P=$(pgrep -f "runtime/bin/Wizard" | head -1)
echo "display: $(ps -o args= -p $P | grep -o 'cocoa,[^ ]*')"
curl -s -m 10 http://127.0.0.1:18930/api/state; echo
cat > /tmp/wd-win.swift <<'SW'
import CoreGraphics
import Foundation
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as! [[String: Any]]
for w in list where (w[kCGWindowOwnerName as String] as? String) == "Wizard" {
  let b = w[kCGWindowBounds as String] as! [String: Any]
  print("window '\(w[kCGWindowName as String] ?? "")' layer=\(w[kCGWindowLayer as String]!) bounds=\(b)")
}
let d = CGDisplayBounds(CGMainDisplayID()); print("screen=\(d.size)")
SW
swift /tmp/wd-win.swift 2>&1 | tail -4
