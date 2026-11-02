#!/bin/bash
# First-chat check for the figlet task.
ex() { python3 -c 'import json,sys;print(json.dumps({"cmd":sys.argv[1],"timeout":60}))' "$1" | curl -s -m 70 -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:18930/api/dev/exec | python3 -c 'import json,sys;print(json.load(sys.stdin).get("out",""))'; }
ex 'pacman -Q figlet 2>&1'
ex "sqlite3 /var/lib/wizard/hermes/state.db \"select content from messages where role='assistant' and content<>'' order by id desc limit 1\" 2>/dev/null | head -c 900"
