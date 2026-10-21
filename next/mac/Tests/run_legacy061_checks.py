#!/usr/bin/env python3
"""Durable-worker entrypoint: native admission regression + unprimed VM probe.
Not a build307, migration, publication or release-acceptance command.
"""
import argparse
import json
import os
from pathlib import Path

import subprocess
import sys

WORK_ROOT = Path(os.environ.get("WIZARD_WORK_ROOT") or Path(os.environ.get("TMPDIR") or "/tmp") / "wizard-work").expanduser().resolve()
WORK_ROOT.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    a = p.parse_args()
    spec = json.loads(a.spec.read_text())
    root = Path(spec['evidenceRoot'])
    source = Path(__file__).resolve().parents[1]
    assert os.uname().sysname == 'Darwin'
    assert source.is_relative_to(WORK_ROOT)
    assert root.resolve().is_relative_to(WORK_ROOT)
    assert not root.exists(), 'New evidence root only'
    assert subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip() == spec['source']
    root.mkdir(parents=True)
    os.chmod(root, 0o700)
    (WORK_ROOT / 'tmp').mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(WORK_ROOT / 'tmp')
    results = {'source': spec['source'], 'upgradeAccepted': False, 'checks': []}
    def save():
        (root / 'checks.json').write_text(json.dumps(results, indent=2) + '\n')
    def check(label, argv, timeout):
        log = root / (label + '.log')
        with log.open('w') as out:
            child = subprocess.Popen(list(map(str, argv)), stdout=out, stderr=subprocess.STDOUT)
            try:
                code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.terminate()  # VM probe catches TERM and performs owned cleanup.
                code = child.wait(timeout=240)
                results['timedOut'] = label
        results['checks'].append({'name': label, 'exitCode': code, 'log': str(log)})
        save()
        if code or results.get('timedOut') == label:
            raise RuntimeError(label + ' failed; see ' + str(log))
    save()
    check('compile-admission', ['xcrun', 'swiftc', '-swift-version', '5', '-target', 'arm64-apple-macos14.0', source / 'Shared/UpdateContract.swift', source / 'Tests/LegacyAdmission/main.swift', '-o', root / 'admission'], 120)
    check('admission', [root / 'admission', root / 'admission-data'], 90)
    # Reuse the accepted modern rollback test; no native production source changes.
    check('compile-activation', ['xcrun', 'swiftc', '-swift-version', '5', '-target', 'arm64-apple-macos14.0', source / 'Shared/DiskIdentity.swift', source / 'App/WizardGuestActivation.swift', source / 'Tests/GuestActivation/main.swift', '-framework', 'AppKit', '-o', root / 'activation'], 120)
    check('activation', [root / 'activation', root / 'activation-data'], 60)
    check('unprimed-direct-replacement', [sys.executable, source / 'Tests/legacy061_probe.py', '--root', root / 'vm', '--baseline-disk', spec['baselineDisk'], '--boot-dir', spec['bootDir'], '--old-app', spec['oldApp'], '--old-launch-app', spec['oldLaunchApp'], '--new-app', spec['newApp'], '--quit-helper', spec['quitHelper'], '--worker-lease', 'inherited'], 1200)
    results['phase'] = 'diagnostic-complete-not-upgrade-acceptance'
    save()
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
