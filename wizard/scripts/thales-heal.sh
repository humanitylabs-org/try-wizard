#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Heal ThalesMedia EINTR: macOS sandboxd wedges on a pending RemovableVolumes
# approval nobody can answer (headless). Killing sandboxd (launchd restarts it)
# clears it. Run on Thales.
ok() { /usr/bin/python3 -c 'import os,sys; os.listdir(sys.argv[1])' "$WIZARD_WORK_ROOT/Projects/wizard-desktop" 2>/dev/null; }
if ok; then echo "thalesmedia=ok"; exit 0; fi
for attempt in 1 2 3; do
  sudo -n /usr/bin/pkill -9 -x sandboxd || true
  sleep 3
  if ok; then echo "thalesmedia=healed attempt=$attempt"; exit 0; fi
done
echo "thalesmedia=still-wedged"; exit 1
