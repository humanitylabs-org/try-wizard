#!/bin/bash
# Drive the real Mizel view inside Wizard.app: New meeting → native capture via window.wizardNative.meetings → Stop.
set -uo pipefail
: "${WIZARD_QA_BASE_URL:?Set WIZARD_QA_BASE_URL to the Wizard origin under test}"
BASE=${WIZARD_QA_BASE_URL%/}
cd "$(dirname "$0")"
ev() { rm -f /tmp/wizard-mvp-qa-eval.txt; ./qa.sh "eval $1"; for i in $(seq 1 30); do sleep 0.2; [[ -s /tmp/wizard-mvp-qa-eval.txt ]] && break; done; cat /tmp/wizard-mvp-qa-eval.txt; echo; }
./qa.sh "connect $BASE/meetings/"
sleep 5
echo "native: $(ev "JSON.stringify({native: window.wizardNative && window.wizardNative.meetings && window.wizardNative.meetings.native, title: document.title})")"
ev "document.querySelector('#btnNew, [data-new], button.new') ? 'has-btn' : [...document.querySelectorAll('button')].map(b=>b.textContent.trim()).filter(Boolean).slice(0,12).join('|')"
ev "(()=>{const b=[...document.querySelectorAll('button')].find(b=>/new meeting/i.test(b.textContent+b.title+(b.getAttribute('aria-label')||''))); if(!b) return 'no-button'; b.click(); return 'clicked';})()"
sleep 4
ev "location.hash"
say -v Samantha -r 180 "This is the other side of the call, speaking through the Mac speakers." &
say -v Daniel -r 180 -a "BlackHole 2ch" "And this is me, talking into the microphone, from the Mizel window."
wait
sleep 6
./qa.sh meeting-state; sleep 0.5; grep -E '"meetingId"|"recording"|"recorderVisible"|"input"|"chunks"' /tmp/wizard-mvp-qa-meeting.json
./qa.sh "snapshot /tmp/wizard-mvp-qa-mizel-recording.png"
sleep 1
ev "(()=>{const b=[...document.querySelectorAll('button')].find(b=>/^stop/i.test((b.textContent||'').trim()+'')||/stop/i.test(b.getAttribute('aria-label')||'')); if(!b) return 'no-stop'; b.click(); return 'stopped';})()"
for i in $(seq 1 40); do sleep 0.5; ./qa.sh meeting-state; sleep 0.2; grep -q '"recording" : false' /tmp/wizard-mvp-qa-meeting.json && break; done
grep -E '"recording"|"spoolPending"' /tmp/wizard-mvp-qa-meeting.json
sleep 3
ev "location.hash"
./qa.sh "snapshot /tmp/wizard-mvp-qa-mizel-after.png"
sleep 1
