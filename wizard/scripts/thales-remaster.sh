#!/bin/bash
# Run on Thales: remaster the Wizard guest inside the wb Colima VM.
set -uo pipefail
source /Volumes/ThalesMedia/Projects/wizard-desktop/env.sh
D=/Volumes/ThalesMedia/Projects/wizard-desktop
docker run --rm --privileged --platform linux/arm64 \
  -v wizwork:/w -v "$D:/d" \
  alpine:3.21 sh /d/scripts/stage1-remaster.sh > "$D/build-remaster.log" 2>&1
echo "exit=$?" >> "$D/build-remaster.log"
