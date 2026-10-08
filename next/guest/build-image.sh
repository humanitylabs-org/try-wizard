#!/bin/bash
# Build the Wizard OS image on Thales (colima docker, arm64).
# Output: $OUT/wizard-os-$VER.tar.xz containing vmlinux, initrd, rootfs.img, manifest.json
set -euo pipefail
. /Volumes/ThalesMedia/Projects/wizard-desktop/env.sh
H=/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-mac
VER=${VER:-0.1.0}
OUT=$H/out; mkdir -p "$OUT" "$H/work"
RUNTIME=/Volumes/ThalesMedia/Projects/wizard-desktop/out/wizard-runtime.tgz
echo "== base image"
docker build -q -t wizard-os-base:$VER "$H/guest"
echo "== export base fs"
cid=$(docker create wizard-os-base:$VER /bin/true)
docker export "$cid" > "$H/work/base.tar"; docker rm "$cid" >/dev/null
cp "$RUNTIME" "$H/work/wizard-runtime.tgz"
echo "== assemble rootfs in privileged alpine"
docker run --rm --privileged -v "$H/work:/w" -v "$H/guest:/g:ro" alpine:3.21 sh -eu -c '
apk add -q e2fsprogs tar xz coreutils shadow file >/dev/null
R=/r; rm -rf $R; mkdir -p $R
tar -xpf /w/base.tar -C $R
tar -xpzf /w/wizard-runtime.tgz -C $R
cp -a /g/overlay/. $R/
chmod 0755 $R/opt/wizard/bin/* $R/usr/local/bin/*; chmod 0644 $R/opt/wizard/bin/wizard-env
chmod 0440 $R/etc/sudoers.d/10-wizard; chown -R root:root $R/etc $R/opt/wizard/bin $R/opt/wizard/setup $R/usr/local/bin
for f in hostname hosts; do cp /g/overlay/etc/$f $R/etc/$f; done
ln -sf /run/systemd/resolve/stub-resolv.conf $R/etc/resolv.conf
mount --bind /dev $R/dev; mount -t proc proc $R/proc; mount -t sysfs sys $R/sys
trap "umount $R/sys $R/proc $R/dev 2>/dev/null || true" EXIT
chroot $R /usr/sbin/useradd -m -u 1000 -U -G sudo -s /bin/bash -c Wizard wizard
chroot $R /usr/bin/passwd -l wizard >/dev/null
chroot $R /usr/bin/passwd -l root >/dev/null
chroot $R /usr/bin/chown -R wizard:wizard /home/wizard /opt/wizard/hermes-agent
echo "vmw_vsock_virtio_transport" >> $R/etc/initramfs-tools/modules
echo "virtio_blk" >> $R/etc/initramfs-tools/modules
echo "virtio_net" >> $R/etc/initramfs-tools/modules
echo "MODULES=most" > $R/etc/initramfs-tools/conf.d/wizard
KV=$(ls $R/lib/modules | head -1); echo kernel $KV
M=$R/lib/modules/$KV/kernel; du -sh $M
for d in drivers/gpu drivers/media drivers/net/wireless drivers/net/ethernet drivers/infiniband drivers/staging drivers/bluetooth drivers/iio drivers/input/touchscreen drivers/hid drivers/usb drivers/sound sound net/wireless net/mac80211 net/bluetooth drivers/scsi drivers/ata drivers/mmc drivers/mtd drivers/isdn drivers/platform drivers/thunderbolt drivers/nfc net/nfc drivers/net/can drivers/remoteproc drivers/leds drivers/spi drivers/i2c; do rm -rf $M/$d; done
chroot $R /usr/sbin/depmod $KV; du -sh $M
rm -rf $R/usr/lib/firmware/* $R/lib/firmware/* 2>/dev/null || true
chroot $R /usr/sbin/update-initramfs -c -k $KV >/dev/null 2>&1 || chroot $R /usr/sbin/update-initramfs -u -k $KV
for u in systemd-networkd systemd-resolved wizard-grow wizard-firstboot wizard-hermes wizard-ux wizard-setup wizard-vsock@8923 wizard-vsock@8930 wizard-ctl systemd-timesyncd serial-getty@hvc0; do
  chroot $R /usr/bin/systemctl enable $u >/dev/null 2>&1 || echo "enable failed: $u"
done
for u in apt-daily.timer apt-daily-upgrade.timer e2scrub_all.timer e2scrub_reap.service fstrim.timer getty@tty1.service; do
  chroot $R /usr/bin/systemctl mask $u >/dev/null 2>&1 || true
done
chroot $R /usr/bin/systemctl set-default multi-user.target >/dev/null
(cd $R/opt/wizard/hermes-agent && chroot $R sh -c "cd /opt/wizard/hermes-agent && /opt/wizard/venv/bin/python -c \"import aiohttp, gateway.platforms.api_server; print(123)\"")
chroot $R /opt/wizard/node/bin/node -v
chroot $R /opt/wizard/venv/bin/python -m py_compile /opt/wizard/setup/server.py && echo setup-compiles
chroot $R /opt/wizard/bin/wizard-firstboot; test -s $R/var/lib/wizard/secrets.env; echo firstboot-ok; rm -f $R/var/lib/wizard/secrets.env
for f in wizard-hermes-start wizard-ux-start wizard-setup-start wizard-firstboot wizard-grow wizard-ctl wizard-open-url; do test -x $R/opt/wizard/bin/$f; done; echo exec-bits-ok
for f in wizard-hermes-start wizard-ux-start wizard-setup-start wizard-firstboot wizard-grow wizard-ctl; do chroot $R bash -n /opt/wizard/bin/$f || exit 1; done; echo scripts-parse
mkdir -p /w/boot
cp $R/boot/initrd.img-$KV /w/boot/initrd
K=$R/boot/vmlinuz-$KV; file $K
if file $K | grep -q gzip; then gunzip -c $K > /w/boot/vmlinux; else cp $K /w/boot/vmlinux; fi
file /w/boot/vmlinux
umount $R/sys $R/proc $R/dev; trap - EXIT
rm -rf $R/boot/*.old $R/tmp/* $R/var/tmp/* $R/var/log/*.log $R/root/.hermes $R/.dockerenv $R/vmlinuz.old $R/initrd.img.old
find $R -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
USED=$(du -sm $R | cut -f1); SIZE=$((USED * 13 / 10 + 512)); echo "rootfs used ${USED}M image ${SIZE}M"
rm -f /w/rootfs.img; truncate -s ${SIZE}M /w/rootfs.img
mkfs.ext4 -q -F -L wizardos -m 1 -E root_owner=0:0 -d $R /w/rootfs.img
e2fsck -fn /w/rootfs.img >/dev/null && echo fsck-clean
rm -rf $R
'
cd "$H/work"
python3 - "$VER" <<'PY'
import json, hashlib, sys, os
v=sys.argv[1]
def sha(p):
    h=hashlib.sha256(); f=open(p,'rb')
    for b in iter(lambda: f.read(1<<20), b''): h.update(b)
    return h.hexdigest()
m={"name":"Wizard OS","version":v,"kernel":"boot/vmlinux","initrd":"boot/initrd","rootfs":"rootfs.img",
   "cmdline":"console=hvc0 root=/dev/vda rw quiet loglevel=3 systemd.show_status=false",
   "files":{p:sha(p) for p in ["boot/vmlinux","boot/initrd","rootfs.img"]},
   "sizes":{p:os.path.getsize(p) for p in ["boot/vmlinux","boot/initrd","rootfs.img"]}}
json.dump(m, open("manifest.json","w"), indent=2); print(json.dumps(m, indent=1))
PY
echo "== compress"
rm -f "$OUT/wizard-os-$VER.tar.xz"
tar -cf - manifest.json boot rootfs.img | xz -T0 -6 > "$OUT/wizard-os-$VER.tar.xz"
shasum -a 256 "$OUT/wizard-os-$VER.tar.xz" | tee "$OUT/wizard-os-$VER.tar.xz.sha256"
ls -la "$OUT"
echo IMAGE_OK
