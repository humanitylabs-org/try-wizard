#!/bin/sh
# Transcriber engine entry on a Try Wizard box (see engine.py). Installs the three pinned Python wheels into the
# app's data folder once, then serves. Runs as uid 1000 with a read-only root; /data is the app's data folder.
set -eu
export HOME=/data UV_CACHE_DIR=/data/.uv-cache PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
PY=/opt/hermes/.venv/bin/python
LIB=/data/pylib-1
stage() {
  "$PY" -c 'import json,os,sys; from pathlib import Path; p=Path("/data/preparation.json"); t=p.with_suffix(".tmp"); t.write_text(json.dumps({"stage":sys.argv[1]})); os.replace(t,p)' "$1"
}
if [ ! -f "$LIB/.ok" ]; then
  stage "installing Python voice runtime"
  echo "voice: installing onnx-asr 0.12.0, onnxruntime 1.31.0, numpy 2.5.4"
  rm -rf "$LIB.tmp"
  n=0
  until uv pip install --quiet --python "$PY" --target "$LIB.tmp" --only-binary :all: \
        onnx-asr==0.12.0 onnxruntime==1.31.0 numpy==2.5.4; do
    n=$((n+1)); [ $n -ge 8 ] && exit 1
    stage "retrying Python runtime download ($n)"
    echo "voice: wheel install failed, retry $n"; rm -rf "$LIB.tmp"; sleep $((n*15))
  done
  rm -rf "$LIB" && mv "$LIB.tmp" "$LIB" && touch "$LIB/.ok" && rm -rf "$UV_CACHE_DIR"
fi
export PYTHONPATH="$LIB"
stage "starting local Parakeet engine"
exec "$PY" /voice/engine.py
