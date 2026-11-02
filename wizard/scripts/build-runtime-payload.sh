#!/bin/bash
# Runs inside an arm64 Arch Linux ARM container (same userland as the guest).
# Produces /out/wizard-runtime.tgz containing /opt/wizard/{venv,hermes-agent,node,ux,python}.
set -euo pipefail
P=/payload
OUT=/out
W=/opt/wizard
mkdir -p "$W" "$OUT"

echo "== base tools"
tar -xzf "$P/dl/uv.tar.gz" -C /tmp
UV=$(find /tmp -maxdepth 3 -type f -name uv | head -1)
"$UV" --version

echo "== node"
mkdir -p "$W/node"
tar -xJf "$P/dl/node.tar.xz" -C "$W/node" --strip-components=1
"$W/node/bin/node" -v

echo "== hermes source"
mkdir -p "$W/hermes-agent"
tar -xzf "$P/hermes-agent.tgz" -C "$W/hermes-agent"

echo "== python (managed, relocatable into /opt/wizard/python)"
export UV_PYTHON_INSTALL_DIR="$W/python"
export UV_CACHE_DIR=/tmp/uv-cache
"$UV" python install 3.12
PY=$("$UV" python find 3.12)
echo "python=$PY"

echo "== venv + deps"
"$UV" venv --python "$PY" "$W/venv"
VIRTUAL_ENV="$W/venv" "$UV" pip install --python "$W/venv/bin/python" -r "$P/requirements.txt"
VIRTUAL_ENV="$W/venv" "$UV" pip install --python "$W/venv/bin/python" --no-deps -e "$W/hermes-agent"

echo "== smoke imports"
cd "$W/hermes-agent"
"$W/venv/bin/python" - <<'PY'
import aiohttp, httpx, openai, yaml
import gateway.platforms.api_server as a
import hermes_cli.free_tier_bootstrap, hermes_cli.anon_auth, hermes_cli.auth_codex
print("imports ok", aiohttp.__version__)
PY

echo "== wizard ux"
mkdir -p "$W/ux/dist"
tar -xzf "$P/ux.tgz" -C "$W/ux"
tar -xzf "$P/ux-dist.tgz" -C "$W/ux/dist"
"$W/node/bin/node" -e "import('/opt/wizard/ux/node_modules/jose/dist/webapi/index.js').then(()=>console.log('jose ok')).catch(e=>{console.error(e);process.exit(1)})" || \
  "$W/node/bin/node" -e "require.resolve('jose',{paths:['/opt/wizard/ux']}); console.log('jose resolvable')"

echo "== trim"
find "$W" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$W/node/include" "$W/node/share/doc" "$W/node/share/man"
du -sh "$W"/* | sort -h

echo "== pack"
tar -C / -czf "$OUT/wizard-runtime.tgz" opt/wizard
ls -la "$OUT/wizard-runtime.tgz"
echo RUNTIME_OK
