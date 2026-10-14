#!/bin/bash
# Read-only historical diagnostics; no process or privacy changes.
set -euo pipefail
ROOT=/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-fix-round-20261014/updater
E="$ROOT/evidence-repair"
mkdir -p "$E"
date -u +%FT%TZ > "$E/diagnostic-start.txt"
/usr/bin/log show --start '2026-10-14 18:43:30' --end '2026-10-14 18:49:00' --style compact --info --debug --predicate '(process == "Autoupdate") OR (process == "Updater") OR (process == "Installer") OR (subsystem CONTAINS "sparkle") OR (eventMessage CONTAINS "org.humanitylabs.wizard.mvp")' > "$E/sparkle-historical.log" 2>&1
/usr/bin/log show --start '2026-10-14 18:10:30' --end '2026-10-14 18:23:30' --style compact --info --debug --predicate '(process == "sandboxd") OR (process == "tccd") OR (eventMessage CONTAINS "mkdir")' > "$E/privacy-historical.log" 2>&1
sudo -n dmesg > "$E/kernel.log"
/usr/bin/python3 - "$E" <<'PY'
import pathlib,subprocess,sys
E=pathlib.Path(sys.argv[1])
for name in ['sparkle-historical.log','privacy-historical.log','kernel.log']:
 s=(E/name).read_text(); lines=s.splitlines(); needles=['sparkle','autoupdate','installer','wizard','watchdog','approval','removable','deny','denied','error','stall']
 selected=[l for l in lines if any(n in l.lower() for n in needles)]
 print(name,'lines',len(lines),'selected',len(selected));print('\n'.join(selected[-160:]))
PY
