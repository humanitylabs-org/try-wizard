#!/bin/bash
# QA: Wizard for Mac 0.5.0 loads Wizard UX (desktop shell) and drives it through the native bridge.
# Bounded: every wait has a deadline. Never sends a message to the agent (orb take is cancelled).
set -uo pipefail
cd ~/build/wizard-ux-desktop/mac
APP="$PWD/dist/Wizard.app"
OLD=$(pgrep -f 'wizard-mizel-mac/mac/dist/Wizard.app/Contents/MacOS/Wizard' | head -1)
defaults export org.humanitylabs.wizard.mvp /tmp/wizard-defaults-backup.plist
restore() {
  pkill -f "$APP/Contents/MacOS/Wizard" 2>/dev/null; sleep 1
  defaults import org.humanitylabs.wizard.mvp /tmp/wizard-defaults-backup.plist
  [[ -n "$OLD" ]] && { open ~/build/wizard-mizel-mac/mac/dist/Wizard.app; echo "restored 0.4.0 test app"; }
}
trap restore EXIT
pkill -f '/Wizard.app/Contents/MacOS/Wizard' 2>/dev/null; sleep 1.5
defaults write org.humanitylabs.wizard.mvp QAHooks -bool true
defaults delete org.humanitylabs.wizard.mvp LegacyUX 2>/dev/null
rm -f /tmp/wizard-mvp-qa-*.json /tmp/wizard-mvp-qa-*.txt /tmp/wizard-mvp-qa-ux-*.png
open -n "$APP"
for i in $(seq 1 30); do sleep 0.5; pgrep -f "$APP/Contents/MacOS/Wizard" >/dev/null && break; done
sleep 2
ev() { rm -f /tmp/wizard-mvp-qa-eval.txt; ./qa.sh "eval $1"; for i in $(seq 1 30); do sleep 0.2; [[ -s /tmp/wizard-mvp-qa-eval.txt ]] && break; done; cat /tmp/wizard-mvp-qa-eval.txt 2>/dev/null; echo; }
ux() { rm -f /tmp/wizard-mvp-qa-ux.json; ./qa.sh ux-state; for i in $(seq 1 20); do sleep 0.2; [[ -s /tmp/wizard-mvp-qa-ux.json ]] && break; done; cat /tmp/wizard-mvp-qa-ux.json 2>/dev/null; echo; }
waitux() { for i in $(seq 1 40); do sleep 0.5; ux >/tmp/ux.out; grep -q '"version"' /tmp/ux.out && { cat /tmp/ux.out; return 0; }; done; cat /tmp/ux.out; return 1; }

echo "== 1 connect to James's Wizard by its legacy address → lands on Wizard UX desktop"
./qa.sh "connect https://private.wizard001.com/wizard/"
waitux && echo PASS_UX_LOADED || echo FAIL_UX_LOADED
ev "location.pathname + ' shell=' + (window.WIZ_SHELL||'') + ' html=' + document.documentElement.dataset.shell"
sleep 2; ./qa.sh "snapshot /tmp/wizard-mvp-qa-ux-desktop.png"; sleep 1.5

echo "== 2 Caps Lock + c / search open → wizard:open (no page navigation)"
ev "(window.__wuxLog=[], window.__p=location.href, 'reset')"
./qa.sh "ux-open /meetings/"; sleep 1.5
ev "JSON.stringify({same: location.href===window.__p, wins: document.querySelectorAll('.win, [data-win]').length, titles: [...document.querySelectorAll('.win .title, .win-title, [data-win] .title')].map(e=>e.textContent.trim()).slice(0,6)})"
./qa.sh "wizard-key c"; sleep 1.5
ev "JSON.stringify({same: location.href===window.__p, wins: document.querySelectorAll('.win, [data-win]').length})"
./qa.sh "snapshot /tmp/wizard-mvp-qa-ux-open.png"; sleep 1.5

echo "== 3 Right ⌘ (orb) → bridge answers; then cancel (nothing is sent)"
./qa.sh "voice-tap cmd"; sleep 3
grep "orb (" ~/Library/Application\ Support/Wizard/logs/*.log 2>/dev/null | tail -2
ev "(()=>{const v=document.querySelector('#voiceTime'); return JSON.stringify({log:(window.__wuxLog||[]).slice(-5), voiceTimeShown: !!(v && v.offsetParent)})})()"
./qa.sh "snapshot /tmp/wizard-mvp-qa-ux-orb.png"; sleep 1.5
ev "(window.dispatchEvent(new CustomEvent('wizard:orb',{detail:{action:'cancel'}})),'cancelled')"

echo "== 4 dictation → composer"
./qa.sh "wizard-key c"; sleep 1.5
./qa.sh "ux-dictation QA dictation probe"; sleep 1.5
cat /tmp/wizard-mvp-qa-dictation.txt 2>/dev/null; echo
ev "(()=>{const t=[...document.querySelectorAll('textarea')].map(x=>x.value).filter(Boolean); return JSON.stringify(t.slice(0,3))})()"
ev "(()=>{for(const x of document.querySelectorAll('textarea')){ if(x.value.includes('QA dictation probe')){x.value=''; x.dispatchEvent(new Event('input',{bubbles:true}));}} return 'cleared'})()"

echo "== 5 legacy opt-out still loads the old UX"
defaults write org.humanitylabs.wizard.mvp LegacyUX -bool true
./qa.sh "connect https://private.wizard001.com/wizard/"; sleep 6
ev "location.pathname + ' wizardUX=' + (!!window.wizardUX)"
defaults delete org.humanitylabs.wizard.mvp LegacyUX
./qa.sh "connect https://private.wizard001.com/wizard/"; waitux >/dev/null && echo BACK_ON_UX
ls -la /tmp/wizard-mvp-qa-ux-*.png
echo QA_DONE
