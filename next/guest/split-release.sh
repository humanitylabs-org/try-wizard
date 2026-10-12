#!/bin/bash
# Split a Wizard OS archive into parts that fit GitHub's 2 GiB release-asset limit, and write the feed
# (latest.json) the Mac app downloads from. The app streams the parts in order into one tar, checks each
# part's SHA-256 as it finishes and the whole archive's SHA-256 at the end.
#
#   split-release.sh <wizard-os-x.tar.xz> <out dir> [part MiB, default 1900] [url prefix, default relative]
#
# Upload every wizard-os-x.tar.xz.partNN plus latest.json to the same folder (or set the url prefix).
# For "Choose Downloaded File…" a user selects all parts at once; the app sorts them by name.
set -euo pipefail
OS=${1:?wizard-os tar.xz}; OUT=${2:?out dir}; MIB=${3:-1900}; PREFIX=${4:-}
mkdir -p "$OUT"
NAME=$(basename "$OS")
VER=$(basename "$OS" .tar.xz | sed 's/^wizard-os-//')
rm -f "$OUT/$NAME".part*
split -b "${MIB}m" -a 2 -d "$OS" "$OUT/$NAME.part"
python3 - "$OS" "$OUT" "$NAME" "$VER" "$PREFIX" <<'PY'
import hashlib, json, os, subprocess, sys, glob
src, out, name, ver, prefix = sys.argv[1:]
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(8 << 20), b''): h.update(b)
    return h.hexdigest()
parts = sorted(glob.glob(os.path.join(out, name + '.part*')))
whole = sha(src)
joined = hashlib.sha256()
rows = []
for p in parts:
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(8 << 20), b''): joined.update(b)
    rows.append({"url": prefix + os.path.basename(p), "bytes": os.path.getsize(p), "sha256": sha(p)})
assert joined.hexdigest() == whole, "parts do not reassemble into the archive"
assert all(r["bytes"] < 2 * 1024**3 for r in rows), "a part is over GitHub's 2 GiB limit"
manifest = json.loads(subprocess.run(["tar", "-xqOf", src, "manifest.json"], capture_output=True, check=True).stdout)
feed = {"version": ver, "sha256": whole, "bytes": os.path.getsize(src),
        "installBytes": manifest.get("installBytes"), "parts": rows}
json.dump(feed, open(os.path.join(out, "latest.json"), "w"), indent=2)
print(json.dumps(feed, indent=2))
print("SPLIT_OK", len(rows), "parts")
PY
