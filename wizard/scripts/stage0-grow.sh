#!/bin/sh
# Stage 0: copy stock rootfs, grow it, show pacman config. Runs in alpine privileged container.
set -eu
apk add -q e2fsprogs e2fsprogs-extra >/dev/null
SIZE_MIB=${SIZE_MIB:-12288}
cp /w/stock.ext4 /w/wizard.ext4
truncate -s $((SIZE_MIB*1024*1024)) /w/wizard.ext4
e2fsck -fy /w/wizard.ext4 >/dev/null 2>&1 || true
resize2fs /w/wizard.ext4
mkdir -p /mnt/r
mount -o loop /w/wizard.ext4 /mnt/r
df -h /mnt/r
echo "== pacman.conf (repos)"; grep -n -E "^\[|^Server|^Include|SigLevel" /mnt/r/etc/pacman.conf
echo "== mirrorlist"; grep -v "^#" /mnt/r/etc/pacman.d/mirrorlist | grep -v "^$" | head
umount /mnt/r
