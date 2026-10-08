#!/bin/bash
# Run on Thales: apply Wizard app patch, build ad-hoc signed Wizard.app with the Wizard guest.
set -uo pipefail
source /Volumes/ThalesMedia/Projects/wizard-desktop/env.sh
D=/Volumes/ThalesMedia/Projects/wizard-desktop
L=$D/build-app-wizard.log
{
  cd "$D/try-omarchy" || exit 1
  python3 "$D/scripts/apply-wizard-app-patch.py" "$D/try-omarchy" || exit 1
  TMPDIR="$D/tmp" macos/build-app.sh --configuration production --sign-identity - --guest-dir "$D/guest-wizard"
  echo "build_rc=$?"
  ls -la dist/release.noindex/
} > "$L" 2>&1
echo "exit=$?" >> "$L"
