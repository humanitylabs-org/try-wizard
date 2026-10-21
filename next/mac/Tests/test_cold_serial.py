#!/usr/bin/env python3
"""Run lightweight Swift fixtures against the actual production serial helper.
No VM, native app build, GUI, guest mutation, sleep or dependency download.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import subprocess

WORK_ROOT = Path(os.environ.get("WIZARD_WORK_ROOT") or Path(os.environ.get("TMPDIR") or "/tmp") / "wizard-work").expanduser().resolve()
WORK_ROOT.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    assert os.uname().sysname == 'Darwin', 'Swift checks run on Thales'
    assert a.out.resolve().is_relative_to(WORK_ROOT)
    a.out.mkdir(parents=True, exist_ok=False)
    mac = Path(__file__).resolve().parents[1]
    host = (mac/'Host/main.swift').read_text()
    start = host.index('final class ColdBootstrapSerial {')
    end = host.index('// MARK: - Wizard OS virtual machine', start)
    helper = host[start:end]
    (a.out/'Serial.swift').write_text('import Foundation\n'+helper)
    (a.out/'main.swift').write_bytes((mac/'Tests/ColdSerial/main.swift').read_bytes())
    # Wiring contracts complement executable helper tests; real VM remains a gate.
    configuration = host[host.index('    private func makeConfiguration()'):host.index('    private func stableMAC()')]
    assert '.write(' not in configuration.replace('try Data().write(to: consoleURL)', '')
    assert 'try Data().write(to: consoleURL)' in configuration
    assert 'fileHandleForReading: coldSerial?.input.fileHandleForReading' in configuration
    assert 'self.coldSerial?.generation == generation, self.state == .starting' in host
    assert 'guard self.vm === virtualMachine else { return }' in host
    assert 'guard vm == nil || vm?.state == .stopped else { return }' in host
    assert 'cancelColdSerialWait()\n        state = .stopping' in host
    assert 'self?.cleanupColdSerial()' in host
    binary = a.out/'cold-serial-checks'
    subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(a.out/'module-cache'),
                    str(a.out/'Serial.swift'),str(a.out/'main.swift'),'-o',str(binary)],check=True)
    result = subprocess.run([str(binary),str(a.out/'fixtures')],check=True,capture_output=True,text=True)
    receipt = {'scope':'production serial helper + source lifecycle assertions; no VM acceptance',
               'hostSHA256':hashlib.sha256(host.encode()).hexdigest(),
               'helperSHA256':hashlib.sha256(helper.encode()).hexdigest(),
               'stdout':result.stdout.strip()}
    (a.out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
