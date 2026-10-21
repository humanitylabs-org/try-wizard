#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Run on Thales: build the arm64 Wizard runtime payload inside the wb Colima VM.
set -uo pipefail
source "$WIZARD_WORK_ROOT/Projects/wizard-desktop/env.sh"
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
mkdir -p "$D/out"
docker run --rm --platform linux/arm64 \
  -v "$D/payload:/payload:ro" -v "$D/scripts:/s:ro" -v "$D/out:/out" \
  debian:bookworm-slim bash -c '
    set -e
    apt-get update -qq >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq xz-utils ca-certificates git >/dev/null
    bash /s/build-runtime-payload.sh' > "$D/build-runtime-payload.log" 2>&1
echo "exit=$?" >> "$D/build-runtime-payload.log"
