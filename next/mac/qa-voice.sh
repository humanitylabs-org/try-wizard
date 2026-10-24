#!/bin/bash
# Voice keys QA: Right ⌥ tap → speak → tap → Wizard STT text; Right ⌘ tap → Wizard orb listening (not sent).
set -uo pipefail
: "${WIZARD_QA_BASE_URL:?Set WIZARD_QA_BASE_URL to the Wizard origin under test}"
BASE=${WIZARD_QA_BASE_URL%/}
cd "$(dirname "$0")"
ev() { rm -f /tmp/wizard-mvp-qa-eval.txt; ./qa.sh "eval $1"; for i in $(seq 1 30); do sleep 0.2; [[ -s /tmp/wizard-mvp-qa-eval.txt ]] && break; done; cat /tmp/wizard-mvp-qa-eval.txt; echo; }
st() { ./qa.sh meeting-state; sleep 0.4; python3 -c 'import json;d=json.load(open("/tmp/wizard-mvp-qa-meeting.json"));print(d["voice"], "hud", d["hudVisible"])'; }
echo "== dictation"
./qa.sh "voice-tap opt"; sleep 1.2; st
./qa.sh "panel-snapshot hud /tmp/wizard-mvp-qa-hud.png"
say -v Daniel -r 175 -a "BlackHole 2ch" "Send the pricing deck to Miguel before Thursday."
sleep 0.5
./qa.sh "voice-tap opt"
for i in $(seq 1 40); do sleep 0.5; ./qa.sh meeting-state; sleep 0.2; grep -q '"mode" : "idle"' /tmp/wizard-mvp-qa-meeting.json && break; done
st
echo "== orb"
./qa.sh "connect $BASE/wizard/"; sleep 6
./qa.sh "voice-tap cmd"; sleep 4
ev "(()=>{const f=document.querySelector('button.voice-fab'); return f ? f.getAttribute('aria-label') : 'no-voice-fab';})()"
./qa.sh "snapshot /tmp/wizard-mvp-qa-orb.png"; sleep 1
st
# Leave without sending anything: reload the page (discards the in-page recording).
./qa.sh "connect $BASE/wizard/"; sleep 3
