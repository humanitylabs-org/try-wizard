#!/bin/bash
# Slim factory acceptance, after qa-fresh.sh reached a first chat (dev shell on):
#   1. what the factory shipped (apps, images, disk, RAM)
#   2. local Parakeet voice arrives in the background, with progress, and transcribes through Wizard's own voice
#      route (Agent Service -> Transcriber MCP front -> engine): compressed (webm), long (>30 s), silence
#   3. the agent's shell is this VM: Hermes runs commands and writes files here over its ssh terminal backend, and
#      builds + runs a small app through the agent (hermes -z, the free brain chosen in onboarding)
#   4. Browser and AI Accounts install explicitly on demand; the Hermes browser runtime and Claude CLI are present
#   5. RAM with voice up
#   qa-slim.sh [evidence dir]
set -u
EV=${1:-/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/evidence/slim}
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$EV"; exec > >(tee "$EV/qa-slim.log") 2>&1
G() { bash "$HERE/qa-guest.sh" "$1"; }
W() { G "sudo -iu wizard env XDG_RUNTIME_DIR=/run/user/1000 bash -lc $(printf '%q' "$1")"; }
ok=1; need() { echo "$2" | grep -qi -- "$1" && echo "PASS $3" || { echo "FAIL $3"; ok=0; }; }
HE='$(docker ps -q --filter label=com.docker.compose.service=hermes-agent-engine)'

echo "== 1. factory contents"
W '/home/wizard/.local/bin/wam apps'
G 'docker ps --format "{{.Names}}\t{{.Image}}"; docker images --format "{{.Repository}}:{{.Tag}}\t{{.Size}}"; df -B1 / | tail -1; du -sb /var/lib/docker /var/lib/containerd 2>/dev/null; free -m'

echo "== 2. voice in the background (local Parakeet)"
t0=$(date +%s); st=""; last=""
for i in $(seq 1 720); do
  st=$(G 'cat /var/lib/wizard/voice.json 2>/dev/null || echo "{}"')
  [ "$st" != "$last" ] && { echo "$(( $(date +%s)-t0 ))s $st"; last="$st"; }
  case "$st" in *'"ready"'*) break;; esac; sleep 5
done
need '"ready"' "$st" "voice installed itself in the background"
G 'journalctl -u wizard-voice --no-pager -o cat | tail -6; du -sh /home/wizard/runtipi/app-data/wizardapps/transcriber/data/voice/* 2>/dev/null'
cd "$(mktemp -d)"
say -o s.aiff "Hey Wizard, remind me to call Miguel tomorrow about the Archimedes release." && afconvert -f WAVE -d LEI16@16000 s.aiff short.wav
say -o l.aiff "Wizard OS is a personal AI server you run by talking to it. It installs on a Mac as a small virtual machine, then moves to an always on computer when you are ready. Each app has an API and a tool interface, so your agent can use it and you can build a new view for it. This sentence makes the recording longer than thirty seconds so the engine cuts it into pieces at a quiet point. One more sentence about the weather in Bangkok, which is hot and humid this week." && afconvert -f WAVE -d LEI16@16000 l.aiff long.wav
/opt/homebrew/bin/ffmpeg -loglevel error -y -i short.wav -c:a libopus short.webm
/opt/homebrew/bin/ffmpeg -loglevel error -y -f lavfi -i anullsrc=r=16000:cl=mono -t 4 silence.wav
U=http://127.0.0.1:48023
for f in short.webm:audio/webm long.wav:audio/wav silence.wav:audio/wav; do
  file=${f%%:*}; ct=${f#*:}; s=$(python3 -c 'import time;print(time.time())')
  r=$(curl -s -m 200 -H "content-type: $ct" --data-binary @"$file" -w ' HTTP=%{http_code}' "$U/wizard/voice/transcribe")
  echo "$file ($(python3 -c "import time;print(round(time.time()-$s,2))")s): $r" | cut -c1-400
  case $file in short.webm) need 'Archimedes' "$r" "voice: short webm through Wizard's voice route";;
                 long.wav) need 'Bangkok' "$r" "voice: long recording (cut into pieces)";;
                 silence.wav) need 'HTTP=400' "$r" "voice: silence gives no words (blank transcription)";; esac
done

echo "== 3. the agent's shell is this VM"
R=$(G "docker exec -u 1000:1000 -e HERMES_HOME=/opt/data $HE sh -c 'grep -A8 \"^terminal:\" /opt/data/config.yaml'")
echo "$R"; need 'backend: "\?ssh' "$R" "Hermes terminal backend is ssh to the VM"
R=$(G "docker exec -u 1000:1000 $HE ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -i /opt/data/.ssh-vm/id_ed25519 wizard@wizard-vm 'hostname; id -un; which git python3 docker; sudo -n true && echo sudo-ok'")
echo "$R"; need 'sudo-ok' "$R" "agent key reaches wizard@wizard-vm with sudo and the VM's tools"
S=$(date +%s)
R=$(G "docker exec -u 1000:1000 -e HERMES_HOME=/opt/data $HE timeout 900 /opt/hermes/.venv/bin/hermes -z 'Use your terminal tool. Create ~/projects/hello-wizard/app.py: a Python 3 standard-library web server on port 8765 that answers every GET with the text hello from the wizard vm. Start it in the background with nohup, then curl http://127.0.0.1:8765 and tell me exactly what it returned and the output of hostname.' --yolo 2>&1 | tail -15")
echo "agent run $(( $(date +%s)-S ))s: $R" | cut -c1-1500
V=$(W 'head -5 ~/projects/hello-wizard/app.py; curl -s -m 5 http://127.0.0.1:8765')
echo "$V"; need 'hello from the wizard vm' "$V" "agent built and ran a small app in the VM (file and process are on the VM)"
W 'pkill -f hello-wizard/app.py || true'

echo "== 4. Browser and AI Accounts install explicitly on demand"
for app in browser wizard-ai-accounts; do
  R=$(W "s=\$(date +%s); /home/wizard/.local/bin/wam install $app >/dev/null 2>&1; echo install_exit=\$? seconds=\$(( \$(date +%s)-s )); /home/wizard/.local/bin/wam apps | grep -w $app")
  echo "$R"; need 'install_exit=0' "$R" "$app installs explicitly on demand"
done
BR=$(G "docker exec $HE sh -c 'hs=\$(ls -d /opt/hermes/.playwright/chromium_headless_shell-*/chrome-*/chrome-headless-shell | head -1); timeout 60 \$hs --no-sandbox --disable-gpu --dump-dom \"data:text/html,<p>CHROMIUM_OK</p>\"'")
need 'CHROMIUM_OK' "$BR" "Hermes browser runtime renders a page"
CL=$(G "docker exec $HE sh -c 'claude --version; ls -ld /claude'")
echo "$CL"; need 'Claude Code' "$CL" "Claude CLI in Hermes (login lives on the shared /claude volume)"

echo "== 5. RAM and disk with everything up"
G 'free -m; df -B1 / | tail -1; docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" | sort -k2 -h | tail -14'
if [ $ok = 1 ]; then echo "QA_SLIM_OK"; else echo "QA_SLIM_FAIL"; exit 1; fi
