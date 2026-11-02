#!/bin/bash
# Build vmrun (headless Virtualization.framework runner for image builds and timing). Ad-hoc signed.
set -euo pipefail
cd "$(dirname "$0")"
xcrun swiftc -O -o vmrun vmrun.swift -framework Virtualization
cat > vmrun.entitlements <<'X'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.apple.security.virtualization</key><true/></dict></plist>
X
codesign -f -s - --entitlements vmrun.entitlements vmrun
rm -f vmrun.entitlements
echo "built $(pwd)/vmrun"
