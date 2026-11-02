#!/bin/bash
# Inspect guest display chain: EDID preferred mode, sync helper result, Hyprland monitor.
cat > /tmp/wd-dx.json <<'J'
{"cmd": "for c in /sys/class/drm/card*-Virtual-*; do echo $c $(cat $c/status); cat $c/modes | head -3; done; U=$(id -u wizard); export XDG_RUNTIME_DIR=/run/user/$U HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/$U/hypr | head -1); ps -o user=,pid=,args= -C bash | grep display-sync; sudo -E -u wizard bash -x /usr/local/bin/omarchy-native-display-sync --once 2>&1 | grep -E 'mode=|scale=|hyprctl|rule=|response' | head -12; sudo -E -u wizard hyprctl monitors | sed -n 2p", "timeout": 40}
J
curl -s -m 60 -X POST -H 'Content-Type: application/json' --data-binary @/tmp/wd-dx.json http://127.0.0.1:18930/api/dev/exec | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("out","")[-3000:]);print(d.get("err","")[-800:])'
