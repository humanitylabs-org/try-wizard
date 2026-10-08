#!/bin/bash
# Poll the booting guest for up to ~7 minutes. Part 3 of the boot test.
D=/Volumes/ThalesMedia/Projects/wizard-desktop
for i in $(seq 1 84); do
  code=$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:18930/healthz)
  if [[ $code == 200 ]]; then
    echo "onboarding up after $((i * 5))s"
    break
  fi
  sleep 5
done
echo "== endpoints"
for p in 18930 18923 18865; do
  printf '%s %s\n' "$p" "$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:$p/healthz)"
done
echo "== state"
curl -s -m 3 http://127.0.0.1:18930/api/state
echo
echo "== helper stderr"
tail -25 "$D/qa/helper-stderr.log" | cut -c1-220
