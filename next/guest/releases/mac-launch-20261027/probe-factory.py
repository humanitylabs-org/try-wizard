#!/usr/bin/env python3
"""Worker-only disposable factory diagnostic; never packages or admits a release.

Use a self-contained pre-repin snapshot, retaining its real image/security receipts.
The explicit grants workaround diagnoses downstream scripts with the old WAM pin;
it is NOT acceptance of the new WAM image or permission policy. Default is read-only.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def load_assembly():
    spec = importlib.util.spec_from_file_location('probe_assembly', HERE / 'assemble.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_owned_stage(root):
    media = Path(os.environ.get('THALES_MEDIA', '/unconfigured-external-media')).resolve()
    assert sys.platform == 'darwin', 'Thales worker only'
    assert root.is_relative_to(media), 'external media required'
    assert root.name == 'diagnostic-stage' and root.parent.parent.name == 'evidence', 'diagnostic snapshot only'
    assert (root / 'preparation').resolve() == HERE, 'execute the snapshot copy of this script'


def offline_identity(assembly, disk, pins):
    result = subprocess.run([assembly.E2 + 'e2fsck', '-fn', str(disk)], capture_output=True, text=True, timeout=300)
    (disk.parents[2] / 'offline-fsck.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    checks = [('cat /etc/machine-id', b'', 'machine identity not sealed'),
              ('cat /home/wizard/wizard-app-manager/SOURCE_COMMIT', (pins['finalPins']['wam'] + '\n').encode(), 'sealed WAM source mismatch')]
    for command, expected, reason in checks:
        row = subprocess.run([assembly.E2 + 'debugfs', '-R', command, str(disk)], capture_output=True, check=True)
        assert row.stdout == expected, reason
    for forbidden in ['/var/lib/wizard/setup.json', '/home/wizard/.wizard-os/private-access.json']:
        row = subprocess.run([assembly.E2 + 'debugfs', '-R', 'stat ' + forbidden, str(disk)], capture_output=True, check=True)
        assert b'File not found' in row.stderr, 'identity survived sealing: ' + forbidden


def execute(root, workaround):
    assert_owned_stage(root)
    assembly = load_assembly()
    pins = json.loads((HERE / 'pins.json').read_text())
    base = pins['assembly']['base']
    original = Path(os.path.expandvars(base['path']))
    assert assembly.sha(original) == base['sha256']
    work = root / 'assembly-work'
    work.mkdir(exist_ok=False)
    work.chmod(0o700)
    assert shutil.disk_usage(work).free > 60 * 1024 ** 3
    for port in [48000, 48023, 48030]:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    proc = None
    receipt = {'diagnosticOnly': True, 'releaseAccepted': False, 'publishing': False,
               'workaround': 'root chmod 0644 of grants while old installer runs' if workaround else None,
               'sources': pins['finalPins'], 'phase': 'starting'}
    def save():
        (work / 'diagnostic-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    save()
    try:
        boot = work / 'data/os/boot'
        boot.mkdir(parents=True)
        disk = work / 'data/os/disk.img'
        assembly.run(['cp', '-c', original, disk])
        disk.chmod(0o600)
        with disk.open('r+b') as stream:
            stream.truncate(48 * 1024 ** 3)
        for name, row in base['boot'].items():
            source = Path(os.path.expandvars(row['path']))
            assert assembly.sha(source) == row['sha256']
            shutil.copy2(source, boot / name)
        host = Path(os.path.expandvars(pins['assembly']['host']['path']))
        assert assembly.sha(host) == pins['assembly']['host']['sha256']
        (work / 'data/os/manifest.json').write_text(json.dumps({'cmdline': 'console=hvc0 root=/dev/vda rw', 'memoryMiB': 4096}))
        (work / 'data/dev-shell').write_text('owned disposable factory diagnostic\n')
        (work / 'data/files-folder.json').write_text(json.dumps({'path': str(root)}))
        release = assembly.runtime_release(pins, root)
        (work / 'runtime-release.json').write_text(json.dumps(release, indent=2) + '\n')
        (work / 'source-pins.json').write_text(json.dumps({'source': pins['finalPins']['native'], **{k: pins['finalPins'][k] for k in ['ux', 'service', 'wam']}}))
        with (work / 'host.stdout').open('w') as out, (work / 'host.stderr').open('w') as err:
            proc = subprocess.Popen([str(host), '--wizard-data-home', str(work / 'data')], stdout=out, stderr=err)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            assert proc.poll() is None
            try:
                assembly.guest('true', 5)
                break
            except (OSError, RuntimeError):
                time.sleep(2)
        else:
            raise TimeoutError('owned diagnostic guest boot')
        assembly.guest('resize2fs /dev/vda; mkdir -p /mnt/launch; mount -t virtiofs wizard-files /mnt/launch; test ! -e /var/lib/wizard/setup.json')
        assembly.guest('python3 /mnt/launch/preparation/guest-apply.py --check-pristine > /mnt/launch/assembly-work/pristine.log 2>&1')
        if workaround:
            assembly.guest("systemd-run --unit=wizard-diagnostic-grants /bin/bash -c 'while :; do if test -f /home/wizard/runtipi/state/wizard-grants.json; then chmod 0644 /home/wizard/runtipi/state/wizard-grants.json; fi; sleep 0.1; done'")
        receipt['phase'] = 'guest-apply'
        save()
        assembly.guest('python3 /mnt/launch/preparation/guest-apply.py --apply > /mnt/launch/assembly-work/apply.log 2>&1', 7200)
        receipt['applyPassed'] = json.loads((work / 'applied.json').read_text())['pristine'] is True
        assert receipt['applyPassed']
        if workaround:
            assembly.guest('systemctl stop wizard-diagnostic-grants')
        receipt['phase'] = 'seal'
        save()
        try:
            assembly.guest('python3 /mnt/launch/preparation/seal-factory.py > /mnt/launch/assembly-work/seal.log 2>&1', 180)
        except (OSError, RuntimeError):
            assert (work / 'factory-sanitization.json').is_file(), 'seal failed before its receipt'
        assert json.loads((work / 'factory-sanitization.json').read_text())['pristine'] is True
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = work / 'data/host-status.json'
            if proc.poll() is not None or (status.exists() and json.loads(status.read_text()).get('state') == 'stopped'):
                break
            time.sleep(1)
        else:
            raise TimeoutError('clean diagnostic shutdown')
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=30)
        offline_identity(assembly, disk, pins)
        receipt.update(phase='seal-and-offline-identity-passed', sealPassed=True, offlineIdentityPassed=True)
    except Exception as error:
        receipt.update(phase='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        if proc and proc.poll() is None:
            try:
                assembly.guest('sync; systemctl poweroff', 20)
            except (OSError, RuntimeError):
                pass
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=30)
        receipt['baseUnchanged'] = assembly.sha(original) == base['sha256']
        # Logs and receipts survive; no disposable 48GiB disk survives the job.
        if work.joinpath('data').exists() and (proc is None or proc.poll() is not None):
            shutil.rmtree(work / 'data')
        receipt['cloneDeleted'] = not (work / 'data').exists()
        save()
    assert receipt['baseUnchanged'] and receipt['cloneDeleted']
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-root', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--diagnostic-grants-workaround', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'diagnosticOnly': True, 'buildStarted': False, 'publishing': False,
                          'steps': ['verify base', 'clone', 'guest-apply', 'seal', 'offline identity checks', 'delete clone'],
                          'grantsWorkaround': args.diagnostic_grants_workaround}))
        return
    execute(args.stage_root.resolve(), args.diagnostic_grants_workaround)


if __name__ == '__main__':
    main()
