#!/usr/bin/env bash
# Local smoke: throwaway HERMES_HOME + standalone API + Wizard UX server, the same shape the VM runs.
set -euo pipefail

SOURCE_HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HA="$SOURCE_HERMES_HOME/hermes-agent"
UX="${WIZARD_UX_DIR:-$HOME/work/wizard-desktop-vm-ux}"
export WIZARD_WORK_ROOT="${WIZARD_WORK_ROOT:-${TMPDIR:-/tmp}/wizard-work}"
mkdir -p "$WIZARD_WORK_ROOT"
ROOT="$WIZARD_WORK_ROOT/wd-smoke"
rm -rf "$ROOT"; mkdir -p "$ROOT/home" "$ROOT/state"
export HERMES_HOME=$ROOT/home HOME=$ROOT HERMES_GUEST_ONBOARDING=1
KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
echo "$KEY" > "$ROOT/key"
cd "$HA"
# bootstrap guest identity + config
./venv/bin/python -c "from hermes_cli.free_tier_bootstrap import run_bootstrap; print(run_bootstrap(announce=False))"
API_SERVER_KEY=$KEY WIZARD_HERMES_API_KEY=$KEY WIZARD_API_HOST=127.0.0.1 WIZARD_API_PORT=18865 \
  nohup ./venv/bin/python "$SOURCE_HERMES_HOME/scripts/wizard-api-standalone.py" > "$ROOT/api.log" 2>&1 &
echo $! > "$ROOT/api.pid"
cd "$UX"
WIZARD_HERMES_API_KEY=$KEY HERMES_ORIGIN=http://127.0.0.1:18865 WIZARD_HOST=127.0.0.1 WIZARD_PORT=18923 \
  WIZARD_REQUIRE_CF_ACCESS=0 WIZARD_STATIC_DIR="$UX/dist" \
  WIZARD_OPERATOR_STATE_PATH=$ROOT/state/op.json WIZARD_THREAD_DISPOSITION_STATE_PATH=$ROOT/state/disp.json \
  WIZARD_AGENT_ARTIFACT_ROOTS=$ROOT WIZARD_HERMES_STATE_PATH=$HERMES_HOME/state.db WIZARD_HELM_DB_PATH=$ROOT/none.db \
  nohup node server/index.mjs > "$ROOT/ux.log" 2>&1 &
echo $! > "$ROOT/ux.pid"
for i in $(seq 1 40); do curl -fsS -o /dev/null http://127.0.0.1:18923/ 2>/dev/null && curl -fsS -o /dev/null -H "Authorization: Bearer $KEY" http://127.0.0.1:18865/health 2>/dev/null && break; sleep 1; done
echo "ux: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18923/)  api: $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" http://127.0.0.1:18865/health)"
tail -3 "$ROOT/api.log"; tail -3 "$ROOT/ux.log"
