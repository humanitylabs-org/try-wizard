#!/bin/bash
# Run a command as root inside the local WizardOS (QA only). Needs the dev shell: create
# "~/Library/Application Support/Wizard/dev-shell" before WizardOS starts (qa-fresh.sh does), then the guest
# listens on vsock 9200 and Wizard Host bridges it to 127.0.0.1:48000.
#   qa-guest.sh 'wam doctor'      (commands run as root; use `sudo -iu wizard ...` for the wizard user)
#   qa-guest.sh < script.sh
set -euo pipefail
PORT=${PORT:-48000}
if [ $# -gt 0 ]; then CMD="$1"; else CMD="$(cat)"; fi
python3 - "$PORT" "$CMD" <<'PY'
import socket, sys
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1800)
s.sendall(("{\n" + sys.argv[2] + "\n} </dev/null 2>&1\nexit\n").encode())
while True:
    b = s.recv(65536)
    if not b: break
    sys.stdout.buffer.write(b); sys.stdout.flush()
PY
