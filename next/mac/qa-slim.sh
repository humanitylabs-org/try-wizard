#!/bin/bash
# Slim factory acceptance, after qa-fresh.sh reached a first chat (dev shell on):
#   1. what the factory shipped (apps, images, disk), 2. voice arrives in the background and transcribes a real
#   recording, 3. Browser and AI Accounts install on first use, 4. the agent's own browser tool runs, 5. memory.
#   qa-slim.sh [evidence dir]
set -u
EV=${1:-/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/evidence/slim}
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$EV"; exec > >(tee "$EV/qa-slim.log") 2>&1
G() { bash "$HERE/qa-guest.sh" "$1"; }
W() { G "sudo -iu wizard env XDG_RUNTIME_DIR=/run/user/1000 bash -lc $(printf '%q' "$1")"; }
ok=1; need() { echo "$2" | grep -q "$1" && echo "PASS $3" || { echo "FAIL $3"; ok=0; }; }

echo "== 1. factory contents (before voice lands)"
W '/home/wizard/.local/bin/wam apps'
G 'docker ps --format "{{.Names}}\t{{.Image}}"; df -B1 / | tail -1; du -sb /var/lib/docker | cut -f1; free -m'
HM=$(G 'docker ps --format "{{.Image}}" --filter label=com.docker.compose.service=hermes-agent-engine')
echo "hermes engine image: $HM"

echo "== 2. voice in the background"
t0=$(date +%s); st=""
for i in $(seq 1 180); do
  st=$(G 'cat /var/lib/wizard/voice.json 2>/dev/null || echo "{}"'); case "$st" in *'"ready"'*) break;; esac; sleep 10
done
echo "voice status after $(( $(date +%s)-t0 ))s (wait only, not since boot): $st"
need '"ready"' "$st" "voice installed itself in the background"
G 'journalctl -u wizard-voice --no-pager -o cat | tail -8'
# A real recording: macOS speech synthesis -> 16 kHz WAV, sent to the transcriber engine from inside the box.
say -o /tmp/wq-voice.aiff "Wizard voice check. The quick brown fox jumps over the lazy dog." && \
  afconvert -f WAVE -d LEI16@16000 /tmp/wq-voice.aiff /tmp/wq-voice.wav && \
  B64=$(base64 -i /tmp/wq-voice.wav | tr -d '\n')
G "echo '$B64' | base64 -d > /tmp/wq-voice.wav; ls -l /tmp/wq-voice.wav"
TX=$(G 'ip=$(docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}" transcriber_wizardapps-transcriber-engine-1 | cut -d" " -f1); for i in $(seq 1 60); do r=$(curl -s -m 120 -F file=@/tmp/wq-voice.wav -F model=Systran/faster-whisper-small http://$ip:8000/v1/audio/transcriptions); case "$r" in *text*) echo "$r"; break;; esac; sleep 5; done')
echo "transcription: $TX"
need -i 'fox' "$TX" "voice transcribes a real recording"

echo "== 3. Browser and AI Accounts install on first use (from the App Store)"
for app in browser wizard-ai-accounts; do
  R=$(W "s=\$(date +%s); /home/wizard/.local/bin/wam install $app >/dev/null 2>&1; echo install_exit=\$? seconds=\$(( \$(date +%s)-s )); /home/wizard/.local/bin/wam apps | grep -w $app")
  echo "$R"; need 'install_exit=0' "$R" "$app installs on first use"
done

echo "== 4. the agent's own browser tool runtime (Playwright headless shell inside Hermes)"
BR=$(G 'docker exec hermes-agent_wizardapps-hermes-agent-engine-1 sh -c "cd /opt/hermes && timeout 120 node -e \"const {chromium}=require(\x27playwright\x27);(async()=>{const b=await chromium.launch();const p=await b.newPage();await p.setContent(\x27<title>wizard-ok</title>\x27);console.log(\x27TITLE\x27,await p.title());await b.close()})().catch(e=>{console.error(e);process.exit(1)})\""')
echo "$BR"; need 'TITLE wizard-ok' "$BR" "Hermes browser runtime launches Chromium"
CL=$(G 'docker exec hermes-agent_wizardapps-hermes-agent-engine-1 sh -c "claude --version; test -f /opt/hermes/plugins/model-providers/claude-subscription-directsdk-experimental/plugin.yaml && echo plugin-ok; ls -ld /claude"')
echo "$CL"; need 'plugin-ok' "$CL" "Claude subscription path present (CLI + DirectSDK plugin + /claude volume)"

echo "== 5. memory with everything installed"
G 'free -m; docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" | sort -k2 -h | tail -12'
[ $ok = 1 ] && echo "QA_SLIM_OK" || echo "QA_SLIM_FAIL"
