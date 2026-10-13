#!/bin/bash
# Developer VM on the build Mac: boot a clone of a built disk with a root shell on vsock 9200.
#   devvm.sh start <disk.img> [share-dir]   clone the disk (APFS clone, instant), boot it in the background
#   devvm.sh sh '<command>'                   run a command as root in the guest, print its output
#   devvm.sh stop
# Bridges: 127.0.0.1:48000 -> dev shell, 47931 -> onboarding (8930), 47924 -> Wizard UX (8923).
set -euo pipefail
W=${W:-/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020}
D=$W/dev; mkdir -p "$D"
VMRUN=$(cd "$(dirname "$0")" && pwd)/vmrun
case "${1:-}" in
start)
  src=${2:?disk}; share=${3:-}
  [ -f "$D/pid" ] && kill "$(cat "$D/pid")" 2>/dev/null && sleep 5 || true
  rm -f "$D/dev.img"; cp -c "$src" "$D/dev.img"
  truncate -s 64g "$D/dev.img"
  args=(--kernel "$W/work/boot/vmlinux" --initrd "$W/work/boot/initrd" --disk "$D/dev.img"
        --cmdline "console=hvc0 root=/dev/vda rw wizard.dev=1" --cpus 4 --mem ${MEM:-6144}
        --console "$D/console.log" --bridge 48000:9200 --bridge 47931:8930 --bridge 47924:8923)
  [ -n "$share" ] && { mkdir -p "$share"; args+=(--share "wizard-files=$share"); }
  nohup "$VMRUN" "${args[@]}" > "$D/vmrun.log" 2>&1 &
  echo $! > "$D/pid"; echo "started pid $(cat "$D/pid")"
  ;;
sh)
  python3 - "$2" <<'PY'
import socket, sys
s = socket.create_connection(("127.0.0.1", 48000), timeout=900)
s.sendall(("{\n" + sys.argv[1] + "\n} </dev/null 2>&1\nexit\n").encode());
while True:
    b = s.recv(65536)
    if not b: break
    sys.stdout.buffer.write(b); sys.stdout.flush()
PY
  ;;
stop)
  [ -f "$D/pid" ] && kill "$(cat "$D/pid")" && rm -f "$D/pid"; echo stopped ;;
*) echo "usage: devvm.sh start <disk> [share] | sh '<cmd>' | stop"; exit 64 ;;
esac
