#!/bin/bash
# Build gate: no installed program may be mostly zero blocks (data lost on the way to the disk image).
# Usage inside a privileged Linux container: check-image.sh <image>  -> exit 1 and a list when any is found.
set -u
IMG=${1:-/w/rootfs.img}
mkdir -p /chk; mount -o ro,noload,loop "$IMG" /chk || exit 2
python3 - /chk <<'PY'
import os, sys
root = sys.argv[1]
bad, n = [], 0
for base in ("var/lib/docker/overlay2", "usr/bin", "usr/lib/aarch64-linux-gnu"):
    for d, _, files in os.walk(os.path.join(root, base)):
        for f in files:
            p = os.path.join(d, f)
            try:
                if os.path.islink(p) or os.path.getsize(p) < (1 << 20): continue  # small arm64 programs are mostly 64K-page padding
                with open(p, "rb") as fh:
                    if fh.read(4) != b"\x7fELF": continue
                    fh.seek(0); data = fh.read()
            except OSError:
                continue
            n += 1
            blocks = [data[i:i + 4096] for i in range(0, len(data) - 4095, 4096)]
            zero = sum(1 for b in blocks if not any(b))
            if blocks and zero * 4 > len(blocks) * 3:   # over 75% zero
                bad.append((p[len(root):], len(data), zero, len(blocks)))
print(f"checked {n} ELF files; {len(bad)} mostly zero")
for p, size, z, t in bad[:15]:
    print(f"  {p} size={size} zero_blocks={z}/{t}")
sys.exit(1 if bad else 0)
PY
rc=$?
umount /chk
exit $rc
