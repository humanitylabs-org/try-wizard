#!/bin/bash
# Build Wizard for Mac 0.5.0 (feature/wizard-ux-desktop). Run on Thales under the worker lock.
set -euo pipefail
cd ~/build/wizard-ux-desktop/mac
chmod +x *.sh
VER=0.5.0 ./build.sh 2>&1 | tail -5
codesign --verify --deep --strict dist/Wizard.app && echo CODESIGN_OK
shasum -a 256 dist/Wizard-0.5.0.dmg
