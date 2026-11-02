#!/bin/sh
# Remaster the stock Try Omarchy factory rootfs into the Wizard guest and pack
# launcher-valid guest artifacts. Runs in a privileged alpine (arm64) container:
#   -v wizwork:/w  -v <project>:/d
set -eu
SIZE_MIB=${SIZE_MIB:-8192}
D=/d
W=/w/wizard.ext4
R=/mnt/g
G=$D/guest-wizard
UP=$D/upstream/guest-v0.5.1
apk add -q e2fsprogs e2fsprogs-extra zstd python3 coreutils tar shadow >/dev/null

echo "== grow image to ${SIZE_MIB} MiB"
cp /w/stock.ext4 "$W"
truncate -s $((SIZE_MIB * 1024 * 1024)) "$W"
e2fsck -fy "$W" >/dev/null 2>&1 || true
resize2fs "$W" >/dev/null
mkdir -p "$R"
mount -o loop "$W" "$R"
mount --bind /dev "$R/dev"
mount -t proc proc "$R/proc"
cleanup() { umount "$R/proc" 2>/dev/null || true; umount "$R/dev" 2>/dev/null || true; umount "$R" 2>/dev/null || true; }
trap cleanup EXIT

echo "== runtime payload -> /opt/wizard"
tar -xzf "$D/out/wizard-runtime.tgz" -C "$R"

echo "== wizard overlay"
cp -a "$D/wizard-overlay/etc/." "$R/etc/"
cp -a "$D/wizard-overlay/opt/." "$R/opt/"
chown -R root:root "$R/etc/systemd/system" "$R/etc/sudoers.d" "$R/etc/sddm.conf.d" "$R/opt/wizard/bin" "$R/opt/wizard/setup" "$R/opt/wizard/share"
chmod 0755 "$R"/opt/wizard/bin/*
chmod 0440 "$R/etc/sudoers.d/10-wizard"
chmod 0644 "$R"/etc/systemd/system/wizard-*.service "$R/etc/sddm.conf.d/10-wizard-autologin.conf"

echo "== wizard user"
chroot "$R" /usr/bin/useradd -m -u 1000 -U -G wheel,audio,video,input,users,render -s /bin/bash -c Wizard wizard
chroot "$R" /usr/bin/passwd -l wizard >/dev/null
cp -a "$D/wizard-overlay/home/wizard/." "$R/home/wizard/"
mkdir -p "$R/home/wizard/.local/state"
chroot "$R" /usr/bin/chown -R wizard:wizard /home/wizard /opt/wizard/hermes-agent

echo "== retire Omarchy first-boot provisioning; enable Wizard services"
rm -f "$R/var/lib/omarchy/provisioning/pending"
rm -f "$R/etc/systemd/system/multi-user.target.wants/omarchy-provision-owner.service"
for unit in wizard-firstboot wizard-hermes wizard-ux wizard-setup wizard-dev-relay; do
  ln -sf "/etc/systemd/system/$unit.service" "$R/etc/systemd/system/multi-user.target.wants/$unit.service"
done
echo wizard > "$R/etc/hostname"
# Hyprland's first-run welcome/update/donate screens would pop over the Wizard.
for b in hyprland-update-screen hyprland-welcome hyprland-donate-screen; do
  [ -e "$R/usr/bin/$b" ] && ln -sf /usr/bin/true "$R/usr/bin/$b"
done
mkdir -p "$R/home/wizard/.local/state/hyprland"
mkdir -p "$R/var/lib/sddm"
printf '[Last]\nSession=omarchy.desktop\nUser=wizard\n' > "$R/var/lib/sddm/state.conf"
chroot "$R" /usr/bin/chown -R sddm:sddm /var/lib/sddm

echo "== guest self-check"
chroot "$R" /usr/bin/id wizard
chroot "$R" /usr/bin/sudo -l -U wizard | tail -2
ls -la "$R/etc/systemd/system/multi-user.target.wants" | grep wizard
chroot "$R" /opt/wizard/venv/bin/python -c "import sys; sys.path.insert(0,'/opt/wizard/hermes-agent'); import aiohttp, gateway.platforms.api_server; print('guest python ok', sys.version.split()[0])"
chroot "$R" /opt/wizard/node/bin/node -v
chroot "$R" /opt/wizard/venv/bin/python -m py_compile /opt/wizard/setup/server.py && echo "setup server compiles"
df -h "$R" | tail -1

echo "== build-spec with new image size"
python3 - "$R/usr/share/try-omarchy/build-spec.json" "$SIZE_MIB" <<'PY'
import json, sys
p, size = sys.argv[1], int(sys.argv[2])
spec = json.load(open(p))
spec["image"]["sizeMiB"] = size
open(p, "w").write(json.dumps(spec, indent=2) + "\n")
print("build-spec sizeMiB", spec["image"]["sizeMiB"])
PY

sync
cleanup
trap - EXIT
e2fsck -fy "$W" >/dev/null 2>&1 || true
e2fsck -fn "$W" >/dev/null && echo "fsck clean"

echo "== pack guest artifacts"
rm -rf "$G"; mkdir -p "$G"
for f in vmlinuz-linux initramfs-linux.img provenance.json LICENSE.omarchy packages.lock.txt; do cp "$UP/$f" "$G/$f"; done
python3 - "$UP/build-spec.json" "$G/build-spec.json" "$SIZE_MIB" <<'PY'
import json, sys
spec = json.load(open(sys.argv[1]))
spec["image"]["sizeMiB"] = int(sys.argv[3])
open(sys.argv[2], "w").write(json.dumps(spec, indent=2) + "\n")
PY
cp "$W" "$G/rootfs.ext4"
zstd --force --quiet -9 --threads=0 "$G/rootfs.ext4" -o "$G/rootfs.ext4.zst"
OMARCHY_BUILDER_IMAGE_DIGEST="sha256:3d66142899d4886f74973b16ae6e028d74ea63270f228279f477bfab335a2c8f" \
  python3 "$D/try-omarchy/guest/scripts/write-guest-manifest.py" --directory "$G" --spec "$G/build-spec.json"
(
  cd "$G"
  sha256sum LICENSE.omarchy build-spec.json guest-manifest.json initramfs-linux.img provenance.json rootfs.ext4 rootfs.ext4.zst vmlinuz-linux > SHA256SUMS
  sha256sum packages.lock.txt >> SHA256SUMS
)
rm -f "$G/rootfs.ext4"
ls -la "$G"
echo REMASTER_OK
