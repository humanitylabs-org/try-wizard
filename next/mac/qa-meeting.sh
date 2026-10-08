#!/bin/bash
# Two-sided meeting QA on Thales (no physical mic: BlackHole 2ch is the default input).
#   Me   = speech played into "BlackHole 2ch" (what the mic hears)
#   Them = speech played to the default output (Mac mini Speakers) — what a call app would play
# Drives the running Wizard.app over its QA channel; prints the meeting id.
set -euo pipefail
cd "$(dirname "$0")"
TITLE=${1:-"Two-sided capture test"}
rm -f /tmp/wizard-qa-meeting.json /tmp/wizard-qa-meeting-stop.json
./qa.sh "meeting-new $TITLE"
for i in $(seq 1 40); do ./qa.sh meeting-state; sleep 0.25; grep -q '"recording" : true' /tmp/wizard-qa-meeting.json 2>/dev/null && break; done
cat /tmp/wizard-qa-meeting.json | head -60
MID=$(python3 -c 'import json;print(json.load(open("/tmp/wizard-qa-meeting.json")).get("meetingId",""))')
echo "MEETING $MID"
[[ -n $MID ]] || exit 1
sleep 1
# Conversation: alternate sides, a little overlap-free.
them() { say -v Samantha -r 175 "$1"; }
me()   { say -v Daniel -r 175 -a "BlackHole 2ch" "$1"; }
them "Hi James, thanks for making time. I wanted to walk through the Mizel launch plan for next week."
me   "Sounds good. The main thing I need from you is the final pricing by Friday."
them "Understood. I will send pricing for the three tiers by Thursday evening, and Miguel will review the onboarding copy."
me   "Great. Let's also agree that the beta goes to twenty testers on Monday."
./qa.sh "meeting-note Pricing due Thursday evening"
them "Agreed, twenty testers on Monday. One risk is the Android build, it still needs signing."
me   "Okay, I will own the Android signing. Let's meet again on Tuesday to check progress."
sleep 1
./qa.sh meeting-state; sleep 0.5; cp /tmp/wizard-qa-meeting.json /tmp/wizard-qa-meeting-live.json
./qa.sh "panel-snapshot recorder /tmp/wizard-qa-recorder.png"
sleep 6
./qa.sh meeting-stop
for i in $(seq 1 120); do sleep 0.5; [[ -s /tmp/wizard-qa-meeting-stop.json ]] && break; done
echo "--- live state"; cat /tmp/wizard-qa-meeting-live.json | head -50
echo "--- stop"; cat /tmp/wizard-qa-meeting-stop.json
echo "MEETING $MID"
