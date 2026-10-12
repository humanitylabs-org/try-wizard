#!/bin/bash
# In-guest acceptance (Wizard OS 0.2 stack) through the QA dev shell (qa-guest.sh):
#   wam doctor all PASS; `wam install` of one store app; Mac-folder ownership; does the agent see the apps' tools?
set -u
EV=${1:-/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/evidence/guest}
APP_TO_INSTALL=${APP_TO_INSTALL:-hermes-frontend-3}
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$EV"; exec > >(tee "$EV/qa-guest-checks.log") 2>&1
G() { bash "$HERE/qa-guest.sh" "$1"; }
W() { G "sudo -iu wizard env XDG_RUNTIME_DIR=/run/user/1000 bash -lc $(printf '%q' "$1")"; }
echo "== versions"
W 'git -C /home/wizard/wizard-app-manager log -1 --format="wizard-app-manager %H %cd"; docker ps --format "{{.Image}}" | sort -u'
echo "== wam doctor"
W '/home/wizard/.local/bin/wam doctor; echo "doctor_exit=$?"'
echo "== wam slots"
W '/home/wizard/.local/bin/wam slots'
echo "== wam install $APP_TO_INSTALL (from the store)"
W "time /home/wizard/.local/bin/wam install $APP_TO_INSTALL; echo install_exit=\$?; /home/wizard/.local/bin/wam apps"
W "docker ps --format '{{.Names}} {{.Status}}' | grep -i ${APP_TO_INSTALL%%-*} || echo 'no container'"
echo "== Mac folder as the media root"
G 'mount | grep -E "mac-files|runtipi/media"; ls -lan /home/wizard/runtipi/media; sudo -u wizard touch /home/wizard/runtipi/media/Inbox/from-guest-wizard.txt && echo wizard-can-write'
G 'docker exec files_wizardapps-files-1 sh -c "id; touch /srv/Exports/from-files-app.txt && echo files-app-can-write; ls -ln /srv | head" 2>&1 | head -12'
G 'docker exec wizard-shell_wizardapps-wizard-shell-1 sh -c "id; ls -ln /media | head -8; touch /media/Inbox/from-shell.txt && echo shell-can-write"'
echo "== app databases stay on the VM disk"
G 'df -h / /home/wizard/runtipi/media | cat; ls -d /home/wizard/runtipi/app-data/*/*; docker inspect runtipi-db --format "{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}"'
echo "== does Hermes (agent slot) have the installed apps' tools?"
G 'docker exec hermes-agent_wizardapps-hermes-agent-engine-1 sh -c "grep -n \"^mcp_servers:\" -A30 /opt/data/config.yaml || echo NO_MCP_SERVERS_IN_HERMES_CONFIG"'
W 'python3 -c "import json;d=json.load(open(\"/home/wizard/.wizard-os/apps.json\"));print([(a[\"id\"],(a.get(\"mcp\") or {}).get(\"url\")) for a in d[\"apps\"]])"'
