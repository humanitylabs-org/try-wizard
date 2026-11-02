#!/bin/bash
# Thales-only, under worker.lock; run production SHA code against an actual factory disk.
set -euo pipefail
cd "$(dirname "$0")"
EV=${1:?evidence dir}; DISK=${2:?factory rootfs}; SHA=${3:?expected SHA256}
mkdir -p "$EV"
python3 - "$EV" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=Path('App/main.swift').read_text(); s=s[:s.index('enum HostControl')]
s+=r'''
let file = URL(fileURLWithPath: CommandLine.arguments[1])
let expected = CommandLine.arguments[2]
for _ in 0..<2 {
    let actual = try OSInstaller.sha256(of: file)
    precondition(actual == expected, "factory SHA mismatch")
}
var usage = rusage()
getrusage(RUSAGE_SELF, &usage)
precondition(usage.ru_maxrss < 256 * 1024 * 1024, "hashing retained multi-GB autoreleased buffers")
print("PRODUCTION_HASH_BOUNDED_OK max_rss_bytes=\(usage.ru_maxrss)")
'''
(p/'main.swift').write_text(s)
PY
xcrun swiftc -O Shared/Shared.swift "$EV/main.swift" -framework AppKit -framework WebKit -framework ServiceManagement -o "$EV/hash-check"
"$EV/hash-check" "$DISK" "$SHA" | tee "$EV/result.log"
