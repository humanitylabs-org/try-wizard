#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# Guest diagnostics through the onboarding dev endpoint + a screendump.
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
ex() { python3 -c 'import json,sys;print(json.dumps({"cmd":sys.argv[1],"timeout":60}))' "$1" | curl -s -m 70 -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:18930/api/dev/exec | python3 -c 'import json,sys;d=json.load(sys.stdin);print("rc",d.get("rc"));print(d.get("out",""))'; }
echo "== services"; ex "systemctl is-active wizard-firstboot wizard-hermes wizard-ux wizard-setup wizard-dev-relay sddm; ss -ltn | grep -E ':(8865|8923|8930|18923|18865) '"
echo "== session"; ex "loginctl list-sessions --no-legend; ps -eo user,pid,args | grep -E '[H]yprland|[c]hromium|[w]izard-kiosk|[u]wsm' | cut -c1-160 | head"
echo "== hypr errors"; ex "cat /home/wizard/.local/state/wizard-hypr-errors.log 2>/dev/null | tail -20; ls /run/user/*/hypr 2>/dev/null"
echo "== sddm log"; ex "journalctl -b -u sddm --no-pager | tail -15"
Q=$(ls -t /tmp/omarchy-qemu-gpu.*/qmp.sock 2>/dev/null | head -1)
python3 "$D/scripts/qmp-screendump.py" "$Q" /tmp/wd-screen.ppm >/dev/null && sips -s format png /tmp/wd-screen.ppm --out /tmp/wd-screen.png >/dev/null && echo screen-ok
