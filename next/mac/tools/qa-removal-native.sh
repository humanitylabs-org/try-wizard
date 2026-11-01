#!/bin/bash
# Run only on a Mac, inside a task-owned source copy, through the durable worker.
# This compiles the real app and runs injected filesystem contracts. It does NOT
# claim the real-VM or native-dialog acceptance in REMOVAL.md.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(uname -s) == Darwin ]] || { printf 'Native acceptance requires macOS\n' >&2; exit 2; }
: "${REMOVAL_EVIDENCE:?Choose a NEW task-owned evidence directory}"
[[ ! -e "$REMOVAL_EVIDENCE" ]] || { printf 'Refusing existing evidence directory\n' >&2; exit 2; }
mkdir -p "$REMOVAL_EVIDENCE"
exec > >(tee "$REMOVAL_EVIDENCE/native.log") 2>&1
bash "$HOME/wd-heal.sh"
df -h /
df -h "$REMOVAL_EVIDENCE"
export SIGN_IDENTITY=- DMG=0
# Caller must supply the verified Sparkle distribution/public key and a QA build number.
bash build.sh
xcrun swiftc -swift-version 5 Shared/RemovalContract.swift Tests/RemovalTests.swift -o "$REMOVAL_EVIDENCE/removal-contract-tests"
"$REMOVAL_EVIDENCE/removal-contract-tests" "$REMOVAL_EVIDENCE/wizard-removal-fixture-$(uuidgen)"
codesign --verify --deep --strict dist/Wizard.app
shasum -a 256 dist/Wizard.app/Contents/MacOS/Wizard \
    "dist/Wizard.app/Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host" \
    Shared/RemovalContract.swift App/WizardRemoval.swift Tests/RemovalTests.swift > "$REMOVAL_EVIDENCE/SHA256SUMS"
printf 'NATIVE_BUILD_AND_CONTRACTS_OK\n'
printf 'NOT_RUN: real-app keep/delete/fresh clicks, onboarding, APFS restore boot, orphan Host <=60s; follow REMOVAL.md numbered checks\n'
