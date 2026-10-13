#!/bin/bash
# Benchmark the current QEMU-based Wizard Desktop on Thales: cold launch until the UX answers, then memory.
H="$HOME/Applications/Wizard.app/Contents/MacOS/omarchy-vm-helper"
pkill -TERM -f "omarchy-vm-helper --run-qemu"; pkill -f "runtime/bin/Wizard -name Wizard"; for i in $(seq 1 30); do pgrep -f "runtime/bin/Wizard -name" >/dev/null || break; sleep 1; done; sleep 2
t0=$(python3 -c 'import time;print(time.time())')
sudo -n launchctl asuser "$(id -u)" sudo -u "$(id -un)" /bin/bash -c "'$H' --run-qemu >/tmp/bench-old-helper.log 2>&1 &"
setup=""; ux=""
for i in $(seq 1 1800); do
  sleep 0.1
  now=$(python3 -c 'import time;print(time.time())')
  if [ -z "$setup" ] && [ "$(curl -s -m 1 -o /dev/null -w '%{http_code}' http://127.0.0.1:18930/)" != "000" ]; then
    setup=$(python3 -c "print('%.1f'%($now-$t0))"); echo "old_onboarding_port_s=$setup"
  fi
  if [ -n "$setup" ] && [ "$(curl -s -m 1 -o /dev/null -w '%{http_code}' http://127.0.0.1:18923/wizard/health)" = "200" ]; then
    ux=$(python3 -c "print('%.1f'%($now-$t0))"); echo "old_ux_ready_s=$ux"; break
  fi
done
[ -z "$ux" ] && echo "old_ux_not_ready_after_180s"
sleep 20
Q=$(pgrep -n -f "runtime/bin/Wizard -name Wizard")
echo "old_qemu_rss_mb=$(( $(ps -o rss= -p $Q) / 1024 ))"
footprint $Q 2>/dev/null | grep -E "phys_footprint:" | head -1
grep -oE -- "-m [^ ]+|-smp [0-9]+" <(ps -o args= -p $Q) | tr '\n' ' '; echo
du -sh "$HOME/Applications/Wizard.app" | cut -f1 | sed 's/^/old_app_size=/'
du -sh "$HOME/Library/Application Support/Wizard/VM" 2>/dev/null | cut -f1 | sed 's/^/old_vm_disk=/'
pkill -TERM -f "omarchy-vm-helper --run-qemu"; pkill -f "runtime/bin/Wizard -name Wizard"
