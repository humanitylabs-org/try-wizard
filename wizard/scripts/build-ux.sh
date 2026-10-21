#!/usr/bin/env bash
# Build Jan's Wizard UX in standalone-device mode for the Wizard Desktop VM.
set -euo pipefail
cd "${WIZARD_UX_DIR:-$HOME/work/wizard-desktop-vm-ux}"
./node_modules/.bin/tsc -b
VITE_WIZARD_DEVICE=standalone ./node_modules/.bin/vite build --outDir .standalone-dist --emptyOutDir
echo "standalone-dist ready: $(du -sh .standalone-dist | cut -f1)"
