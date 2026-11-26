#!/bin/bash
# Runs inside the stand-in guest (test_guest_dns_boot.py). The NAT DNS becomes a fake that truncates every answer
# (a Tailscale Mac, try-wizard#155), then: what Docker hands the engine container, and whether a container on a
# compose network (the engine's place) resolves and reaches portal.nousresearch.com, as Start free needs.
set +e
IP=$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1)
python3 /standin/fake-nat-dns.py "$IP" &
sleep 1
resolvectl dns eth0 "$IP"
resolvectl flush-caches
echo "cmdline: $(tr '\0' ' ' </proc/1/cmdline)"
echo "engine-dns: $(grep '^nameserver' /run/systemd/resolve/resolv.conf | awk '{print $2}' | tr '\n' ' ')"
echo "guest-lookup: $(timeout 15 getent -s dns hosts portal.nousresearch.com >/dev/null 2>&1 && echo ok || echo failed)"
dockerd >/tmp/dockerd.log 2>&1 &
for _ in $(seq 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
docker load -q -i /standin-image/alpine.tar >/dev/null
docker network create wizardapps-standin >/dev/null
docker run --rm --network wizardapps-standin alpine:3 sh -c '
  timeout 15 getent hosts portal.nousresearch.com >/dev/null && echo "engine-lookup: ok" || echo "engine-lookup: failed"
  code=$(timeout 20 wget -q -S -O /dev/null https://portal.nousresearch.com/ 2>&1 | awk "/HTTP\\//{print \$2; exit}")
  echo "engine-https: ${code:-none}"'
