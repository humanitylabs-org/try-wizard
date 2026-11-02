#!/bin/bash
# Engineer launches this only when the account owner is ready at Thales.
# Human signs in directly to GitHub in the visible native window, not in chat.
set -euo pipefail
cd "$(dirname "$0")"
D="$PWD/evidence/human-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$D"
WIZARD_SPIKE_AUTH_SECONDS=900 ./evidence/PrivateDownloadSpike \
 'https://github.com/login?return_to=%2Fhumanitylabs-org%2Ftry-wizard%2Freleases%2Ftag%2Fmac-mvp-0.6.0' \
 https://github.com/humanitylabs-org/try-wizard/releases/tag/mac-mvp-0.6.0 \
 "$D/wizard-os-0.3.0.tar.xz" \
 https://github.com/humanitylabs-org/try-wizard/releases/download/mac-mvp-0.6.0/wizard-os-0.3.0.tar.xz > "$D/native.log" 2>&1
python3 - "$D/receipt.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
d=[v for v in r if v.get('downloadFinished')]
assert len(d)==1, 'No private GitHub download completed; see native receipt'
assert d[0]['bytes']==1269879876
assert d[0]['sha256']=='f2bbbbb18800d369925b95ba3d5be7c0ea11820a967b2ce3c6f2e0f6a2ec4d0e'
print('REAL_PRIVATE_GITHUB_NATIVE_DOWNLOAD_PASS',sys.argv[1])
PY
