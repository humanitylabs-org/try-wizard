#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Persistence test: quit Wizard (SIGTERM -> clean VM shutdown), relaunch, verify state survived.
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
H=$(pgrep -f "Wizard.app/Contents/MacOS/omarchy-vm-helper" | head -1)
echo "helper=$H"
kill -TERM "$H"
for i in $(seq 1 60); do pgrep -f "runtime/bin/Wizard" >/dev/null || break; sleep 2; done
echo "qemu stopped after $((i*2))s"
pgrep -fl "Wizard.app" | head -3
bash "$D/scripts/thales-launch.sh"
for i in $(seq 1 60); do
  c=$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:18930/healthz)
  [ "$c" = 200 ] && { echo "back up after $((i*5))s"; break; }
  sleep 5
done
curl -s -m 10 http://127.0.0.1:18930/api/state; echo
curl -s -m 10 -o /dev/null -w 'front door -> %{http_code} %{redirect_url}\n' http://127.0.0.1:18930/
bash "$D/scripts/thales-first-chat.sh" | head -3
