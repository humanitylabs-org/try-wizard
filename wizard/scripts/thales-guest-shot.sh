#!/bin/bash
: "${WIZARD_WORK_ROOT:?set WIZARD_WORK_ROOT to a work disk}"
# In-guest screenshot via grim in the wizard user's Hyprland session; copies PNG back over the dev endpoint.
D="$WIZARD_WORK_ROOT/Projects/wizard-desktop"
ex() { python3 -c 'import json,sys;print(json.dumps({"cmd":sys.argv[1],"timeout":60}))' "$1" | curl -s -m 70 -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:18930/api/dev/exec | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("out",""))'; }
ex "which grim hyprctl; R=/run/user/1000; S=\$(ls \$R/hypr | head -1); export XDG_RUNTIME_DIR=\$R HYPRLAND_INSTANCE_SIGNATURE=\$S WAYLAND_DISPLAY=wayland-1; ls \$R | grep wayland; hyprctl clients | grep -E 'class|title|fullscreen|size' | head -12; grim -t jpeg -q 55 /tmp/wd.jpg && base64 -w0 /tmp/wd.jpg > /tmp/wd.b64 && wc -c /tmp/wd.b64"
ex "cat /tmp/wd.b64" | base64 -d > /tmp/wd-guest.jpg 2>/dev/null
ls -la /tmp/wd-guest.jpg
