#!/bin/bash
# QA-only (Thales): pre-grant the test build's privacy permissions so headless runs don't block on prompts
# nobody can click. Real users get the normal macOS prompts. Grants are bound to this build's cdhash.
# usage: qa-grant.sh <path/to/Wizard.app> [grant|revoke]
set -euo pipefail
APP=${1:?app}; MODE=${2:-grant}
BID=org.humanitylabs.wizard.mvp
REQ=$(codesign -d -r- "$APP" 2>&1 | sed -n 's/^#* *designated => //p')
echo "$REQ" | csreq -r- -b /tmp/wizard-mvp-qa-req.bin
HEX=$(xxd -p /tmp/wizard-mvp-qa-req.bin | tr -d '\n')
UDB="$HOME/Library/Application Support/com.apple.TCC/TCC.db"
SDB="/Library/Application Support/com.apple.TCC/TCC.db"
NOW=$(date +%s)
row() { echo "INSERT OR REPLACE INTO access (service,client,client_type,auth_value,auth_reason,auth_version,csreq,policy_id,indirect_object_identifier_type,indirect_object_identifier,flags,last_modified,boot_uuid,last_reminded) VALUES ('$1','$BID',0,2,3,1,X'$HEX',NULL,0,'UNUSED',0,$NOW,'UNUSED',$NOW);"; }
if [[ $MODE == grant ]]; then
  sqlite3 "$UDB" "$(row kTCCServiceMicrophone) $(row kTCCServiceAudioCapture)"
  # System-DB services (Accessibility, Input Monitoring, Screen Recording) are SIP-protected: grant those by hand.
  sudo -n sqlite3 "$SDB" "$(row kTCCServiceAccessibility) $(row kTCCServiceListenEvent) $(row kTCCServicePostEvent)" 2>/dev/null || echo "system TCC is SIP-protected: Accessibility/Input Monitoring need a manual grant"
else
  sqlite3 "$UDB" "DELETE FROM access WHERE client='$BID';"
  sudo -n sqlite3 "$SDB" "DELETE FROM access WHERE client='$BID';" 2>/dev/null || true
fi
killall -u "$USER" tccd 2>/dev/null || true
sudo -n killall tccd 2>/dev/null || true
sqlite3 "$UDB" "SELECT service,auth_value FROM access WHERE client='$BID'"
sudo -n sqlite3 "$SDB" "SELECT service,auth_value FROM access WHERE client='$BID'" 2>/dev/null || true
echo "requirement: $REQ"
