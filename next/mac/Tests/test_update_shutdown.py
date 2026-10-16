#!/usr/bin/env python3
"""Actual Host stop/prepareUpdate -> actual activation, with fake VZ I/O only.
Lightweight Swift fixture on Thales; no VM, app build or GUI session.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True); a = p.parse_args()
    assert os.uname().sysname == 'Darwin' and a.out.resolve().is_relative_to('/Volumes/ThalesMedia')
    a.out.mkdir(parents=True, exist_ok=False)
    mac = Path(__file__).resolve().parents[1]
    host = (mac/'Host/main.swift').read_text()
    stop = host[host.index('    func stop(completion:'):host.index('    func runGuestPatch(')]
    prepare = host[host.index('    private func prepareUpdate()'):host.index('    func refresh()')]
    # Only timing and bundle I/O differ; do not replace force policy or responses.
    assert stop.count('.now() + 90') == 1
    stop = stop.replace('.now() + 90', '.now() + 0.01')
    bundle = 'Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().standardizedFileURL.path'
    assert prepare.count(bundle) == 1
    prepare = prepare.replace(bundle, 'Bundle.main.bundleURL.standardizedFileURL.path')
    template = (mac/'Tests/UpdateShutdown/main.swift').read_text()
    (a.out/'main.swift').write_text(template.replace('// PRODUCTION_STOP', stop).replace('// PRODUCTION_PREPARE', prepare))
    subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(a.out/'module-cache'),
                    str(mac/'Shared/DiskIdentity.swift'),str(mac/'App/WizardGuestActivation.swift'),
                    str(a.out/'main.swift'),'-framework','AppKit','-o',str(a.out/'checks')], check=True)
    result = subprocess.run([str(a.out/'checks'),str(a.out/'fixtures')],check=True,capture_output=True,text=True)
    receipt = {'scope':'actual production stop + prepareUpdate + activation; fake VZ I/O, accelerated deadline, fixture bundle path',
               'hostSHA256':hashlib.sha256(host.encode()).hexdigest(),
               'activationSHA256':hashlib.sha256((mac/'App/WizardGuestActivation.swift').read_bytes()).hexdigest(),
               'fixtureSHA256':hashlib.sha256((a.out/'main.swift').read_bytes()).hexdigest(), 'stdout':result.stdout.strip()}
    (a.out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt))


if __name__ == '__main__': main()
