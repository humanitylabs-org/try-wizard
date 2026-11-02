#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Run on Thales: remaster the Wizard guest inside the wb Colima VM.
set -uo pipefail
source "$WIZARD_WORK_ROOT/Projects/wizard-desktop/env.sh"
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
docker run --rm --privileged --platform linux/arm64 \
  -v wizwork:/w -v "$D:/d" \
  alpine:3.21 sh /d/scripts/stage1-remaster.sh > "$D/build-remaster.log" 2>&1
echo "exit=$?" >> "$D/build-remaster.log"
