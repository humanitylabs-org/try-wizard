#!/bin/bash
# QA: install Wizard OS from a file in ~/Downloads (GitHub release path), with the feed unreachable.
set -u
# Corrupt-file rejection: unpack should refuse an archive whose manifest hashes don't match.
mkdir -p /tmp/wbad && (cd /tmp/wbad && rm -rf * && echo '{"files":{"rootfs.img":"00"}}' > manifest.json && echo junk > rootfs.img && tar -cJf /tmp/wizard-os-bad.tar.xz manifest.json rootfs.img ) && echo "bad archive staged"
W=/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-mac
AS="$HOME/Library/Application Support/Wizard"
APP="$HOME/Applications/WizardNext/Wizard.app"
pkill -x Wizard; pkill -TERM -f "Wizard Host.app/Contents/MacOS"
for i in $(seq 1 30); do pgrep -f "Wizard Host.app/Contents/MacOS" >/dev/null || break; sleep 1; done
rm -rf "$AS/os" "$AS/logs" "$AS/host-status.json"
defaults delete org.humanitylabs.wizard >/dev/null 2>&1 || true
rm -rf "$APP"; ditto "$W/mac/dist/Wizard.app" "$APP"
defaults write org.humanitylabs.wizard QAHooks -bool true
t0=$(python3 -c 'import time;print(time.time())')
open "$APP"; sleep 2; cd $W/mac; bash qa.sh choose-this-mac-offline >/dev/null 2>&1
sleep 12; bash qa.sh "snapshot /tmp/wq-getos.png" >/dev/null; sleep 1; bash qa.sh state >/dev/null; python3 -c "import json;d=json.load(open('/tmp/wizard-qa-state.json'));print('feed-unreachable screen:',d['title'],'|',d['subtitle'][:160].replace(chr(10),' / '))"
bash qa.sh "install-file /tmp/wizard-os-bad.tar.xz" >/dev/null; sleep 4; bash qa.sh state >/dev/null; python3 -c "import json;d=json.load(open('/tmp/wizard-qa-state.json'));print('bad-file screen:',d['title'],'|',d['subtitle'][:90].replace(chr(10),' / '))"
t0=$(python3 -c 'import time;print(time.time())')
cp "$W/out/wizard-os-0.1.0.tar.xz" /tmp/wizard-os-0.1.0.tar.xz; bash qa.sh "install-file /tmp/wizard-os-0.1.0.tar.xz" >/dev/null
while python3 -c "import time,sys;sys.exit(0 if time.time()-$t0<180 else 1)"; do
  sleep 1; /tmp/wizard-qa-post state 2>/dev/null; sleep 0.1
  python3 -c "import json,sys;d=json.load(open('/tmp/wizard-qa-state.json'));sys.exit(0 if d['overlayHidden'] or d['title'].startswith(('Can','Wizard OS didn','Setup didn')) else 1)" 2>/dev/null && break
done
python3 -c "import json,time;d=json.load(open('/tmp/wizard-qa-state.json'));print('offline_install_to_window_s=%.1f'%(time.time()-$t0),'|',d['title'],'|',d['subtitle'][:80],'|',d['url'])"
curl -s http://127.0.0.1:47830/healthz; echo
defaults delete org.humanitylabs.wizard osFeedURL
