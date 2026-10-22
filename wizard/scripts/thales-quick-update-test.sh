#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Test the quick-update path on Thales: serve the app tarball locally, update the installed 0.1.1
# in ~/Applications, launch, and check the window is free-form and a normal size.
set -uo pipefail
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
cd "$D/try-omarchy/dist" || exit 1
python3 -m http.server 18777 --bind 127.0.0.1 >/dev/null 2>&1 &
SRV=$!
sleep 1
export WIZARD_APP="$HOME/Applications/Wizard.app" WIZARD_UPDATE_BASE=http://127.0.0.1:18777
OPEN_BIN=/usr/bin/open
# Launch through the captured-stderr path (GUI session) instead of `open`, which needs a login session.
sed 's#^open "\$APP"$#echo READY_TO_OPEN#' "$D/scripts/update-0.1.2.sh" > /tmp/wd-update.sh
bash /tmp/wd-update.sh 2>&1 | tr '\r' '\n' | grep -v '^#' | tail -8
kill $SRV
defaults read com.aiwizards.desktop CFBundleShortVersionString >/dev/null 2>&1
/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$WIZARD_APP/Contents/Info.plist"
codesign --verify --deep --strict "$WIZARD_APP" && echo "codesign ok after update"
strings -a "$WIZARD_APP/Contents/Resources/runtime/bin/Wizard" 2>/dev/null | grep -c '^WizardWindow$' || \
  strings -a "$(find "$WIZARD_APP/Contents/Resources/runtime/bin" -type f | head -1)" | grep -c '^WizardWindow$'
python3 "$D/scripts/set-dev-forwards.py" >/dev/null && echo "dev forwards set"
bash "$D/scripts/thales-launch.sh"
for i in $(seq 1 40); do
  curl -s -o /dev/null -m 2 http://127.0.0.1:18930/api/state && { echo "guest up after $((i*3))s"; break; }
  sleep 3
done
sleep 8
python3 - <<'PY'
import Quartz
for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
    if w.get('kCGWindowOwnerName') == 'Wizard' and w.get('kCGWindowLayer') == 0:
        print('window', dict(w['kCGWindowBounds']))
from AppKit import NSScreen
f = NSScreen.mainScreen().visibleFrame()
print('visible', f.size.width, f.size.height)
PY
curl -s -m 5 http://127.0.0.1:18930/api/state | head -c 200; echo
