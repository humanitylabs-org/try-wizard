#!/usr/bin/env bash
# Local onboarding smoke: fresh HERMES_HOME + Hermes API + Wizard UX + onboarding server.
set -euo pipefail

SOURCE_HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HA="$SOURCE_HERMES_HOME/hermes-agent"
UX="${WIZARD_UX_DIR:-$HOME/work/wizard-desktop-vm-ux}"
SETUP="${WIZARD_SETUP_SCRIPT:-$HOME/work/wizard-desktop/wizard-overlay/opt/wizard/setup/server.py}"
export WIZARD_WORK_ROOT="${WIZARD_WORK_ROOT:-${TMPDIR:-/tmp}/wizard-work}"
mkdir -p "$WIZARD_WORK_ROOT"
ROOT="$WIZARD_WORK_ROOT/wd-onb"
for p in api api-child ux setup; do [ -f "$ROOT/$p.pid" ] && kill "$(cat "$ROOT/$p.pid")" 2>/dev/null || true; done
sleep 1
rm -rf "$ROOT"; mkdir -p "$ROOT/hermes" "$ROOT/ux"
KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))'); echo "$KEY" > "$ROOT/key"
export HOME="$ROOT" HERMES_HOME="$ROOT/hermes" HERMES_GUEST_ONBOARDING=1 WIZARD_ROOT=$ROOT
export WIZARD_HERMES_API_KEY=$KEY API_SERVER_KEY=$KEY
# Hermes API (restart = kill + respawn via this script's loop file)
cat > "$ROOT/run-api.sh" <<EOF
#!/usr/bin/env bash
cd "$HA"
export HOME="$ROOT" HERMES_HOME="$ROOT/hermes" HERMES_GUEST_ONBOARDING=1 WIZARD_HERMES_API_KEY=$KEY API_SERVER_KEY=$KEY WIZARD_API_HOST=127.0.0.1 WIZARD_API_PORT=18865
while true; do
  "$HA/venv/bin/python" "$SOURCE_HERMES_HOME/scripts/wizard-api-standalone.py" >> "$ROOT/api.log" 2>&1 &
  echo \$! > "$ROOT/api-child.pid"
  wait \$!
  sleep 1
done
EOF
cat > "$ROOT/restart-api.sh" <<EOF
#!/usr/bin/env bash
kill "\$(cat "$ROOT/api-child.pid")" 2>/dev/null || true
EOF
chmod +x "$ROOT/restart-api.sh"
chmod +x "$ROOT/run-api.sh"
setsid nohup "$ROOT/run-api.sh" >/dev/null 2>&1 & echo $! > "$ROOT/api.pid"
cd "$UX"
HERMES_ORIGIN=http://127.0.0.1:18865 WIZARD_HOST=127.0.0.1 WIZARD_PORT=18923 WIZARD_REQUIRE_CF_ACCESS=0 \
  WIZARD_STATIC_DIR="$UX/.standalone-dist" \
  WIZARD_OPERATOR_STATE_PATH=$ROOT/ux/op.json WIZARD_THREAD_DISPOSITION_STATE_PATH=$ROOT/ux/disp.json \
  WIZARD_AGENT_ARTIFACT_ROOTS=$ROOT WIZARD_HERMES_STATE_PATH=$ROOT/hermes/state.db WIZARD_HELM_DB_PATH=$ROOT/ux/none.db \
  setsid nohup node server/index.mjs > "$ROOT/ux.log" 2>&1 & echo $! > "$ROOT/ux.pid"
cd "$HA"
WIZARD_SETUP_HOST=127.0.0.1 WIZARD_SETUP_PORT=18930 WIZARD_UX_ORIGIN=http://127.0.0.1:18923 WIZARD_HERMES_ORIGIN=http://127.0.0.1:18865 \
  WIZARD_HERMES_RESTART_CMD="$ROOT/restart-api.sh" WIZARD_OPEN_URL_CMD=/bin/false \
  setsid nohup "$HA/venv/bin/python" "$SETUP" > "$ROOT/setup.log" 2>&1 & echo $! > "$ROOT/setup.pid"
for i in $(seq 1 60); do
  curl -fsS -o /dev/null http://127.0.0.1:18930/healthz 2>/dev/null && curl -fsS -o /dev/null -H "Authorization: Bearer $KEY" http://127.0.0.1:18865/health 2>/dev/null && break; sleep 1
done
echo "setup=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18930/healthz) api=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" http://127.0.0.1:18865/health) ux=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18923/)"
