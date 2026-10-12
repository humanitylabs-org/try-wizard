#!/bin/bash
# Read-only breakdown of a Wizard OS factory rootfs: per-image sizes, volumes, app data, models.
# usage (Thales): bash inspect-rootfs.sh <dir containing rootfs.img>
set -u
. /Volumes/ThalesMedia/Projects/wizard-desktop/env.sh >/dev/null 2>&1
W=${1:?dir}
colima ssh -p wb -- sudo bash -s "$W" <<'EOF'
set -u
W=$1; M=/mnt/wos-inspect
mkdir -p $M; umount $M 2>/dev/null
mount -o ro,loop,noload "$W/rootfs.img" $M || { echo MOUNT_FAIL; exit 1; }
trap 'umount $M' EXIT
echo "== filesystem"; df -B1 $M | tail -1
echo "== top dirs (MB)"; du -x -d1 -m $M 2>/dev/null | sort -n | tail -8
echo "== docker (MB)"; du -s -m $M/var/lib/docker/overlay2 $M/var/lib/docker/volumes $M/var/lib/docker/image 2>/dev/null
echo "== runtipi app-data (MB)"; du -s -m $M/home/wizard/runtipi/app-data/*/* 2>/dev/null | sort -n | tail -12
echo "== models"
find $M/home/wizard/runtipi $M/var/lib/docker/volumes -xdev -type d -name 'models--*' 2>/dev/null | while read d; do du -s -m "$d"; done
echo "== images (uncompressed MB, per repo:tag) via layer dirs"
python3 - $M <<'PY'
import json, os, sys, glob
m = sys.argv[1]
root = f"{m}/var/lib/docker/image/overlay2"
repos = json.load(open(f"{root}/repositories.json"))["Repositories"]
def dirsize(p):
    t = 0
    for dp, dn, fn in os.walk(p):
        for f in fn:
            try: t += os.lstat(os.path.join(dp, f)).st_blocks * 512
            except OSError: pass
    return t
cache = {}
seen_layers = set()
rows = []
by_img = {}
for repo, tags in repos.items():
    for ref, img in tags.items():
        if img not in by_img or "@" in by_img[img]: by_img[img] = ref
for img, ref in by_img.items():
    if True:
        cfg = json.load(open(f"{root}/imagedb/content/sha256/{img.split(':')[1]}"))
        diff = cfg["rootfs"]["diff_ids"]
        # chain ids
        import hashlib
        chain = []; prev = None
        for d in diff:
            cid = d if prev is None else "sha256:" + hashlib.sha256(f"{prev} {d}".encode()).hexdigest()
            chain.append(cid); prev = cid
        total = own = 0
        for cid in chain:
            p = f"{root}/layerdb/sha256/{cid.split(':')[1]}/cache-id"
            if not os.path.exists(p): continue
            cache_id = open(p).read().strip()
            if cache_id not in cache: cache[cache_id] = dirsize(f"{m}/var/lib/docker/overlay2/{cache_id}/diff")
            total += cache[cache_id]
            if cache_id not in seen_layers: own += cache[cache_id]; seen_layers.add(cache_id)
        rows.append((total, own, ref))
for t, o, r in sorted(rows, reverse=True):
    print(f"{t/1e6:8.0f} MB total {o/1e6:8.0f} MB not-shared-before  {r}")
PY
EOF
