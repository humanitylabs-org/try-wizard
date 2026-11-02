#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export TMPDIR="$PWD/evidence/tmp"
mkdir -p "$TMPDIR" evidence/fixture evidence/github
xcrun swiftc -swift-version 5 -target arm64-apple-macos14.0 main.swift -framework AppKit -framework WebKit -o evidence/PrivateDownloadSpike
python3 fixture.py > evidence/fixture/server.log 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true' EXIT
for n in {1..30}; do curl -fsS http://127.0.0.1:48937/health >/dev/null && break; sleep 1; done
rm -f evidence/fixture/download.bin
./evidence/PrivateDownloadSpike http://127.0.0.1:48937/signin http://127.0.0.1:48937/release "$PWD/evidence/fixture/download.bin" http://127.0.0.1:48937/asset > evidence/fixture/native.log 2>&1
python3 -c 'import json,hashlib; r=json.load(open("evidence/fixture/receipt.json")); d=[v for v in r if v.get("downloadFinished")]; assert len(d)==1 and d[0]["sha256"]==hashlib.sha256(b"explicit-local-session-fixture\n"*1024).hexdigest(); print("NATIVE_SESSION_DOWNLOAD_FIXTURE_PASS")'
curl --max-time 20 -sS -o /dev/null -w 'direct-private-asset-unauthenticated: %{http_code}\n' https://github.com/humanitylabs-org/try-wizard/releases/download/mac-mvp-0.6.0/wizard-os-0.3.0.tar.xz > evidence/github/unauthenticated.txt
./evidence/PrivateDownloadSpike 'https://github.com/login?return_to=%2Fhumanitylabs-org%2Ftry-wizard%2Freleases%2Ftag%2Fmac-mvp-0.6.0' https://github.com/humanitylabs-org/try-wizard/releases/tag/mac-mvp-0.6.0 "$PWD/evidence/github/wizard-os-0.3.0.tar.xz" https://github.com/humanitylabs-org/try-wizard/releases/download/mac-mvp-0.6.0/wizard-os-0.3.0.tar.xz > evidence/github/native.log 2>&1
printf 'ROUTE_SPIKE_FINISHED\n'
