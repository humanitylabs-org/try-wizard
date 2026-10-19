#!/bin/bash
# Write the Wizard OS download feed (latest.json) the Mac app reads, plus the files it names.
#   - An archive no bigger than the part size ships as one file (`url`).
#   - A bigger one is cut into ordered ….tar.xz.partNN files (`parts`). Default 240 MiB: Cloudflare caches files
#     under 512 MB at its edge and the R2 upload API takes up to ~250 MiB per request; the app streams them in
#     order into one tar, checks each part's SHA-256 as it ends and the whole archive's SHA-256 at the end.
#   - `background` lists what Wizard OS fetches by itself after first launch (voice), so the app can say up front
#     how much space Wizard will take in total. Override with BACKGROUND_JSON='[...]'.
#
#   split-release.sh <wizard-os-x.tar.xz> <out dir> [part MiB, default 240] [url prefix, default relative]
set -euo pipefail
OS=${1:?wizard-os tar.xz}; OUT=${2:?out dir}; MIB=${3:-240}; PREFIX=${4:-}
# Voice = local Parakeet (TDT 0.6B v2, INT8): 661 MB model + about 40 MB of Python wheels to download; 0.63 GB model
# + 0.12 GB wheels on disk. It runs on the Hermes image already on the box (no extra image).
BACKGROUND_JSON=${BACKGROUND_JSON:-'[{"label":"voice","bytes":705000000,"installBytes":790000000}]'}
mkdir -p "$OUT"
NAME=$(basename "$OS")
VER=$(basename "$OS" .tar.xz | sed 's/^wizard-os-//')
rm -f "$OUT/$NAME" "$OUT/$NAME".part*
SIZE=$(stat -f %z "$OS" 2>/dev/null || stat -c %s "$OS")
if [ "$SIZE" -le $(( MIB * 1024 * 1024 )) ]; then
  cp -c "$OS" "$OUT/$NAME" 2>/dev/null || cp "$OS" "$OUT/$NAME"
else
  split -b "${MIB}m" -a 2 -d "$OS" "$OUT/$NAME.part"
fi
python3 - "$OS" "$OUT" "$NAME" "$VER" "$PREFIX" "$BACKGROUND_JSON" <<'PY'
import hashlib, json, os, subprocess, sys, glob
src, out, name, ver, prefix, background = sys.argv[1:]
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(8 << 20), b''): h.update(b)
    return h.hexdigest()
whole = sha(src)
manifest = json.loads(subprocess.run(["tar", "-xqOf", src, "manifest.json"], capture_output=True, check=True).stdout)
feed = {"version": ver, "sha256": whole, "bytes": os.path.getsize(src), "installBytes": manifest.get("installBytes"),
        "background": json.loads(background)}
parts = sorted(glob.glob(os.path.join(out, name + '.part*')))
if parts:
    joined = hashlib.sha256(); rows = []
    for p in parts:
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(8 << 20), b''): joined.update(b)
        rows.append({"url": prefix + os.path.basename(p), "bytes": os.path.getsize(p), "sha256": sha(p)})
    assert joined.hexdigest() == whole, "parts do not reassemble into the archive"
    assert all(r["bytes"] < 500 * 1000**2 for r in rows), "a part is over 500 MB: Cloudflare would not cache it at the edge"
    feed["parts"] = rows
else:
    assert sha(os.path.join(out, name)) == whole
    feed["url"] = prefix + name
json.dump(feed, open(os.path.join(out, "latest.json"), "w"), indent=2)
print(json.dumps(feed, indent=2))
print("FEED_OK", "parts" if parts else "single file")
PY
