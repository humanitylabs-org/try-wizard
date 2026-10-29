#!/bin/sh
# Copy the shared phone-connect component from wizard-ux into Mac onboarding's vendor folder and record where it
# came from. Onboarding runs in the guest's own setup page, outside wizard-ux, so it carries a copy of the same file
# Settings and the Setup app load (wizard-ux web/core/phone-connect.{js,css}, plus the kit's web/kit/controls.css). Never edit the copies here: change
# wizard-ux, then re-run this with that commit.
#   next/guest/tools/sync-phone-connect.sh <wizard-ux checkout> <commit>
set -eu
UX=${1:?wizard-ux checkout}; REF=${2:?wizard-ux commit}
HERE=$(cd "$(dirname "$0")/.." && pwd); DEST="$HERE/overlay/opt/wizard/setup/static/vendor"
SHA=$(git -C "$UX" rev-parse --verify "$REF^{commit}")
for f in phone-connect.js phone-connect.css; do git -C "$UX" show "$SHA:web/core/$f" > "$DEST/$f"; done
# The component's buttons and cards use the shared kit controls (.wz-button, .wz-card, .wz-row).
git -C "$UX" show "$SHA:web/kit/controls.css" > "$DEST/controls.css"
python3 - "$DEST" "$SHA" <<'PY'
import hashlib, json, sys
from pathlib import Path
dest, sha = Path(sys.argv[1]), sys.argv[2]
paths = {"phone-connect.js": "web/core/phone-connect.js", "phone-connect.css": "web/core/phone-connect.css",
         "controls.css": "web/kit/controls.css"}
files = {f: hashlib.sha256((dest / f).read_bytes()).hexdigest() for f in paths}
doc = {"source": "humanitylabs-org/wizard-ux", "paths": paths, "commit": sha, "sha256": files,
       "note": "Vendored by next/guest/tools/sync-phone-connect.sh. Do not edit; change wizard-ux and re-sync."}
(dest / "phone-connect.provenance.json").write_text(json.dumps(doc, indent=2) + "\n")
print("phone-connect", sha[:9], files)
PY
