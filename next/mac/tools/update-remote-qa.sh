#!/bin/bash
# Thales only, called under the shared worker.lock; no local build fallback.
set -euo pipefail
ROOT=/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-fix-round-20261014/updater
printf 'LOCK_ACQUIRED %s\n' "$(date -u +%FT%TZ)"
cd "$ROOT/sparkle"
if [[ ! -d Sparkle.framework ]]; then
  curl -fL --retry 2 -o Sparkle-2.10.0.tar.xz https://github.com/sparkle-project/Sparkle/releases/download/2.10.0/Sparkle-2.10.0.tar.xz
  test "$(shasum -a 256 Sparkle-2.10.0.tar.xz | cut -d' ' -f1)" = c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c
  tar xf Sparkle-2.10.0.tar.xz
fi
export UPDATER_ROOT="$ROOT" RELEASE_ID=mac-mvp-updater-20261014-staged
/usr/bin/python3 "$ROOT/source/next/mac/tools/update-qa-retire-initializer.py"
/usr/bin/python3 "$ROOT/source/next/mac/tools/update-qa-recover.py"
/usr/bin/python3 "$ROOT/source/next/mac/tools/update-native-qa.py"
