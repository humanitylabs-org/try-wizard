#!/bin/bash
# Real installer low-space regression. Runs only on a Mac whose installation volume
# has less than 16 GiB available. Compiles the production installer, then asserts
# file installation rejects before creating staging or changing the existing disk.
set -euo pipefail
cd "$(dirname "$0")"
EV=${1:?evidence directory}
mkdir -p "$EV"
python3 - "$EV" <<'PY'
from pathlib import Path
import sys, tempfile
p=Path(sys.argv[1]); source=Path('App/main.swift').read_text()
qa=Path(tempfile.mkdtemp(prefix='WizardCapacityQA-', dir=Path.home()/'Library/Caches'))
(qa/'os').mkdir(); (qa/'os/disk.img').write_bytes(b'preserve-capacity-sentinel')
(qa/'os-staging').mkdir()
# Compile the production installer unchanged against an isolated real low-space
# support directory; never point this destructive regression at the live guest.
shared=Path('Shared/Shared.swift').read_text()
shared=shared.replace('return base.appendingPathComponent("Wizard", isDirectory: true)',
                      'return URL(fileURLWithPath: '+__import__('json').dumps(str(qa))+', isDirectory: true)')
(p/'Shared.swift').write_text(shared)
(p/'qa-support-path').write_text(str(qa))
prefix=source.split('// MARK: - Host control')[0]
# The next top-level section follows the installer; derive it from HostControl.
if 'enum HostControl' in prefix:
    prefix=source[:source.index('enum HostControl')]
test=r'''
let installer = OSInstaller()
let fm = FileManager.default
let support = WizardShared.supportDir
let disk = WizardShared.osDir.appendingPathComponent("disk.img")
let staging = OSInstaller.staging
let beforeDisk = try? fm.attributesOfItem(atPath: disk.path)
let beforeStaging = try? fm.attributesOfItem(atPath: staging.path)
let free = try support.deletingLastPathComponent().resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage!
guard free < (16 << 30) else { fatalError("QA requires a genuinely low-space installation volume") }
var finished = false
var message = ""
installer.onDone = { error in
    message = error?.localizedDescription ?? "UNEXPECTED_SUCCESS"
    finished = true
}
installer.install(from: URL(fileURLWithPath: "/nonexistent-capacity-test.tar.xz"))
let deadline = Date().addingTimeInterval(20)
while !finished && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.1)) }
guard finished && message.contains("free space") else { fatalError("Unexpected installer result: \(message)") }
let afterDisk = try? fm.attributesOfItem(atPath: disk.path)
let afterStaging = try? fm.attributesOfItem(atPath: staging.path)
for key in [FileAttributeKey.systemFileNumber, .size, .modificationDate] {
    guard String(describing: beforeDisk?[key]) == String(describing: afterDisk?[key]),
          String(describing: beforeStaging?[key]) == String(describing: afterStaging?[key]) else {
        fatalError("Low-space rejection mutated disk or staging")
    }
}
print("PRODUCTION_FILE_INSTALL_CAPACITY_OK free=\(free) rejection=\(message)")
'''
(p/'main.swift').write_text(prefix+test)
PY
xcrun swiftc -O "$EV/Shared.swift" "$EV/main.swift" -framework AppKit -framework WebKit -framework ServiceManagement -o "$EV/check-capacity"
"$EV/check-capacity" | tee "$EV/qa-capacity.log"
