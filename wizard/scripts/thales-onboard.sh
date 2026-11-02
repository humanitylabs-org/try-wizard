#!/bin/bash
# Drive onboarding inside the real VM through its own HTTP API, then reload the kiosk.
B=http://127.0.0.1:18930
j() { curl -s -m "${3:-200}" -X POST -H 'Content-Type: application/json' -d "$2" "$B$1"; echo; }
t0=$(date +%s)
echo "== name";   j /api/name '{"name":"Merlin"}' 30
echo "== brain";  j /api/brain '{"kind":"free"}' 200
echo "== verify"; j /api/verify '{}' 240
echo "== finish"; j /api/finish '{}' 60
echo "elapsed=$(( $(date +%s) - t0 ))s"
