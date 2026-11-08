#!/bin/bash
# Build the WizardOS image on an Apple Silicon Mac (Thales): Docker (colima) for the file system work,
# Virtualization.framework (mac/tools/vmrun) for the install itself.
#
#   1. base:      Debian 13 arm64 + kernel + Wizard overlay, as an ext4 disk (Docker)
#   2. provision: boot that disk in a real VM; it runs `curl -fsSL aiwizards.com/os.sh | bash` (fresh mode:
#                 Docker, Runtipi, Wizard App Manager, the default app in every spot, images pulled), checks it,
#                 strips per-box identity and powers off (guest/overlay/opt/wizard/bin/wizard-provision)
#   3. pack:      shrink + zero the free space, manifest with per-file SHA-256, wizard-os-<ver>.tar.xz
#
# Output: $OUT/wizard-os-$VER.tar.xz (+ .sha256), $OUT/provision-$VER.json (timings, pins, doctor output).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Optional machine-local Docker/PATH setup; other Macs can export their own environment.
if [ -n "${WIZARD_BUILD_ENV:-}" ]; then . "$WIZARD_BUILD_ENV"; fi
VER=${VER:-0.2.0}
W=${W:-$HERE/../../out/wizard-os-build}   # must be inside Docker/colima's shared mount
BUILD_SOURCE_SHA=${BUILD_SOURCE_SHA:-$(git -C "$HERE" rev-parse HEAD)}
COLIMA_PROFILE=${COLIMA_PROFILE:-wb}
OUT=$W/out; WORK=$W/work; mkdir -p "$OUT" "$WORK"
# Pins (WizardOS release 0.2.0 + wizard-app-manager main).
WAM_COMMIT=${WAM_COMMIT:-1eab0eb991e4031f3fd992c9745f0f9d9f4bfd7a}
WAM_IMAGE=${WAM_IMAGE:-ghcr.io/humanitylabs-org/wizard-app-manager@sha256:8afef790d701d8bdd6728187f943c5d4de50cd09da5dc29f245f636af32c1117}
BUILD_DISK_GB=${BUILD_DISK_GB:-48}
# Slim factory (default): voice, Browser and AI Accounts are left out of the download (voice installs itself after
# first launch). FACTORY=full keeps every default app. HERMES_IMAGE pins the Hermes engine image (slim build).
FACTORY=${FACTORY:-slim}
HERMES_IMAGE=${HERMES_IMAGE:-}
VMRUN=$HERE/../mac/tools/vmrun
STEP=${1:-all}
t() { date +%s; }

if [ "$STEP" = all ] || [ "$STEP" = base ]; then
echo "== 1. base image"
colima status -p "$COLIMA_PROFILE" >/dev/null 2>&1 || colima start -p "$COLIMA_PROFILE"
docker build -q -t wizard-os-base:$VER "$HERE"
cid=$(docker create wizard-os-base:$VER /bin/true)
docker export "$cid" > "$WORK/base.tar"; docker rm "$cid" >/dev/null
rm -rf "$WORK/g"; mkdir -p "$WORK/g"; cp -R "$HERE/overlay" "$WORK/g/overlay"; cp "$HERE/check-image.sh" "$WORK/g/"
# A locally built engine image (docker save) rides into the build disk and is loaded during provisioning.
if [ -n "${HERMES_IMAGE_TAR:-}" ]; then cp "$HERMES_IMAGE_TAR" "$WORK/g/hermes-image.tar"; fi
printf 'WAM_COMMIT=%s\nWAM_IMAGE=%s\nHERMES_IMAGE=%s\nFACTORY=%s\n' "$WAM_COMMIT" "$WAM_IMAGE" "$HERMES_IMAGE" "$FACTORY" > "$WORK/g/provision.env"
docker run --rm --privileged -e GB=$BUILD_DISK_GB -v "$WORK:/w" alpine:3.21 sh -eu -c '
apk add -q e2fsprogs tar coreutils shadow file >/dev/null
R=/r; rm -rf $R; mkdir -p $R
tar -xpf /w/base.tar -C $R
cp -a /w/g/overlay/. $R/
chmod 0755 $R/opt/wizard/bin/* $R/usr/local/bin/*; chmod 0644 $R/opt/wizard/bin/wizard-env
chmod 0440 $R/etc/sudoers.d/10-wizard; chown -R root:root $R/etc $R/opt/wizard $R/usr/local/bin
for f in hostname hosts; do cp /w/g/overlay/etc/$f $R/etc/$f; done
ln -sf /run/systemd/resolve/stub-resolv.conf $R/etc/resolv.conf
mount --bind /dev $R/dev; mount -t proc proc $R/proc; mount -t sysfs sys $R/sys
trap "umount $R/sys $R/proc $R/dev 2>/dev/null || true" EXIT
# uid 1000 `wizard`: the user os.sh installs WizardOS as, and the owner of the shared Mac folder.
chroot $R /usr/sbin/useradd -m -u 1000 -U -G sudo -s /bin/bash -c Wizard wizard
chroot $R /usr/bin/passwd -l wizard >/dev/null
chroot $R /usr/bin/passwd -l root >/dev/null
install -d -m 0750 -o 1000 -g 1000 $R/var/lib/wizard
chmod 0644 $R/etc/docker/daemon.json
install -m 0644 /w/g/provision.env $R/var/lib/wizard/provision.env
if [ -f /w/g/hermes-image.tar ]; then install -d -m 0755 $R/var/lib/wizard/images; mv /w/g/hermes-image.tar $R/var/lib/wizard/images/hermes.tar; fi
mkdir -p $R/home/wizard/runtipi/media && chown -R 1000:1000 $R/home/wizard
for m in vmw_vsock_virtio_transport virtio_blk virtio_net virtiofs; do echo $m >> $R/etc/initramfs-tools/modules; done
echo "MODULES=most" > $R/etc/initramfs-tools/conf.d/wizard
KV=$(ls $R/lib/modules | head -1); echo kernel $KV
M=$R/lib/modules/$KV/kernel
for d in drivers/gpu drivers/media drivers/net/wireless drivers/net/ethernet drivers/infiniband drivers/staging drivers/bluetooth drivers/iio drivers/input/touchscreen drivers/hid drivers/usb drivers/sound sound net/wireless net/mac80211 net/bluetooth drivers/scsi drivers/ata drivers/mmc drivers/mtd drivers/isdn drivers/platform drivers/thunderbolt drivers/nfc net/nfc drivers/net/can drivers/remoteproc drivers/leds drivers/spi drivers/i2c; do rm -rf $M/$d; done
chroot $R /usr/sbin/depmod $KV
rm -rf $R/usr/lib/firmware/* $R/lib/firmware/* 2>/dev/null || true
chroot $R /usr/sbin/update-initramfs -c -k $KV >/dev/null 2>&1 || chroot $R /usr/sbin/update-initramfs -u -k $KV
for u in systemd-networkd systemd-resolved systemd-timesyncd serial-getty@hvc0 wizard-grow wizard-firstboot wizard-media \
         wizard-setup wizard-vsock@8930 wizard-ux-bridge wizard-ctl wizard-dev wizard-provision wizard-voice; do
  chroot $R /usr/bin/systemctl enable $u >/dev/null 2>&1 || { echo "enable failed: $u"; exit 1; }
done
for u in apt-daily.timer apt-daily-upgrade.timer e2scrub_all.timer e2scrub_reap.service fstrim.timer getty@tty1.service; do
  chroot $R /usr/bin/systemctl mask $u >/dev/null 2>&1 || true
done
chroot $R /usr/bin/systemctl set-default multi-user.target >/dev/null
chroot $R python3 -m py_compile /opt/wizard/setup/server.py && echo setup-compiles
for f in $R/opt/wizard/bin/*; do head -1 $f | grep -q bash && { chroot $R bash -n /opt/wizard/bin/$(basename $f) || exit 1; }; done; echo scripts-parse
mkdir -p /w/boot
cp $R/boot/initrd.img-$KV /w/boot/initrd
K=$R/boot/vmlinuz-$KV
if file $K | grep -q gzip; then gunzip -c $K > /w/boot/vmlinux; else cp $K /w/boot/vmlinux; fi
file /w/boot/vmlinux
umount $R/sys $R/proc $R/dev; trap - EXIT
rm -rf $R/boot/*.old $R/tmp/* $R/var/tmp/* $R/var/log/*.log $R/.dockerenv
find $R -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
rm -f /w/build.img; truncate -s ${GB}G /w/build.img
mkfs.ext4 -q -F -L wizardos -m 1 -E root_owner=0:0 -d $R /w/build.img
e2fsck -fn /w/build.img >/dev/null && echo fsck-clean
rm -rf $R
'
rm -f "$WORK/base.tar"
fi

if [ "$STEP" = all ] || [ "$STEP" = provision ]; then
echo "== 2. provision in a VM (os.sh fresh install)"
[ -x "$VMRUN" ] || bash "$HERE/../mac/tools/build-vmrun.sh"
s=$(t)
"$VMRUN" --kernel "$WORK/boot/vmlinux" --initrd "$WORK/boot/initrd" --disk "$WORK/build.img" \
  --cmdline "console=hvc0 root=/dev/vda rw wizard.provision=1" --cpus 4 --mem 8192 \
  --console "$WORK/provision-console.log" --timeout 7200 || { echo "provision VM exited $?"; tail -50 "$WORK/provision-console.log"; exit 1; }
echo "provision VM ran $(( $(t) - s ))s"
grep -a -q PROVISION_OK "$WORK/provision-console.log" || { grep -a -E "PROVISION_FAIL|error" "$WORK/provision-console.log" | tail -20; exit 1; }
fi

if [ "$STEP" = all ] || [ "$STEP" = pack ]; then
echo "== 3. shrink, manifest, compress"
cp "$HERE/check-image.sh" "$WORK/g/"
docker run --rm --privileged -v "$WORK:/w" debian:trixie bash -euc '
apt-get update -qq >/dev/null && apt-get install -y -qq e2fsprogs zerofree >/dev/null
# The provisioned disk must come back clean: any repair here means writes were lost in the VM.
e2fsck -fn /w/build.img > /w/fsck-build.txt 2>&1 || { echo "build.img is not clean:"; tail -20 /w/fsck-build.txt; exit 1; }
echo "build.img fsck clean"
for f in provision.json provision-doctor.txt provision-containers.txt provision-images.txt; do
  debugfs -R "cat /var/lib/wizard/$f" /w/build.img > /w/$f 2>/dev/null || true
done
rm -f /w/rootfs.img; cp --sparse=always /w/build.img /w/rootfs.img
# resize2fs needs a fresh recorded check on the copy. Only fsck 0/1 are acceptable;
# then require a read-only clean pass (never hide a failed repair).
rc=0; e2fsck -fy /w/rootfs.img > /w/fsck-copy.txt 2>&1 || rc=$?
[ "$rc" -le 1 ] || { cat /w/fsck-copy.txt; exit 1; }
e2fsck -fn /w/rootfs.img >> /w/fsck-copy.txt 2>&1 || { cat /w/fsck-copy.txt; exit 1; }
resize2fs -M /w/rootfs.img >/dev/null 2>&1 || { echo "resize2fs -M failed"; resize2fs -M /w/rootfs.img; exit 1; }
BS=$(dumpe2fs -h /w/rootfs.img 2>/dev/null | sed -n "s/^Block size: *//p"); BC=$(dumpe2fs -h /w/rootfs.img 2>/dev/null | sed -n "s/^Block count: *//p")
# 2 GiB of headroom so the first boot has room before the Mac grows the disk.
NEW=$(( BC + 2*1024*1024*1024/BS )); resize2fs /w/rootfs.img $NEW >/dev/null 2>&1
zerofree /w/rootfs.img
truncate -s $(( NEW * BS )) /w/rootfs.img
e2fsck -fn /w/rootfs.img >/dev/null && echo fsck-clean
apt-get install -y -qq python3 >/dev/null
bash /w/g/check-image.sh /w/rootfs.img
FREE=$(dumpe2fs -h /w/rootfs.img 2>/dev/null | sed -n "s/^Free blocks: *//p")
echo $(( (NEW - FREE) * BS )) > /w/used-bytes
echo "rootfs $(( NEW * BS / 1048576 )) MiB, used $(( (NEW - FREE) * BS / 1048576 )) MiB"
'
cp "$WORK/provision.json" "$OUT/provision-$VER.json"
cd "$WORK"
python3 - "$VER" "$BUILD_SOURCE_SHA" <<'PY'
import json, hashlib, sys, os
v = sys.argv[1]
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
files = ["boot/vmlinux", "boot/initrd", "rootfs.img"]
m = {"name": "WizardOS", "version": v, "stack": "wizard-os-0.2-runtipi",
     "sourceCommit": sys.argv[2],
     "kernel": "boot/vmlinux", "initrd": "boot/initrd", "rootfs": "rootfs.img",
     "cmdline": "console=hvc0 root=/dev/vda rw quiet loglevel=3 systemd.show_status=false",
     "memoryMiB": 6144,
     # Space the unpacked image takes on the Mac (used blocks; the rest of rootfs.img unpacks as holes).
     "installBytes": int(open("used-bytes").read()) + os.path.getsize("boot/vmlinux") + os.path.getsize("boot/initrd"),
     "files": {p: sha(p) for p in files}, "sizes": {p: os.path.getsize(p) for p in files}}
try: m["provision"] = json.load(open("provision.json"))
except Exception: pass
json.dump(m, open("manifest.json", "w"), indent=2); print(json.dumps({k: m[k] for k in ("version", "sizes")}, indent=1))
PY
echo "compress"; s=$(t)
rm -f "$OUT/wizard-os-$VER.tar.xz"
# GNU tar with sparse entries: the free space of rootfs.img (zeroed above) becomes holes, so the Mac's tar
# (libarchive) writes only the used blocks when it unpacks. That roughly halves the disk needed to install.
docker run --rm -v "$WORK:/w:ro" debian:trixie tar -C /w --sparse --hole-detection=raw -cf - manifest.json boot rootfs.img \
  | xz -T0 -6 > "$OUT/wizard-os-$VER.tar.xz"
echo "compressed in $(( $(t) - s ))s"
shasum -a 256 "$OUT/wizard-os-$VER.tar.xz" | tee "$OUT/wizard-os-$VER.tar.xz.sha256"
ls -la "$OUT"
echo IMAGE_OK
fi
