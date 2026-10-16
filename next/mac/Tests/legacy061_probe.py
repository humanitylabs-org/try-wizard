#!/usr/bin/env python3
"""Bounded original-disk/direct-replacement diagnostic; NOT upgrade acceptance.

Run only on Thales via wizard_heavy_submit (the durable worker owns worker.lock).
All parameters are explicit; no default owner disk or installed app is selected.
Only an APFS clone is booted. The original apps, disk and factory stay untouched.
No maintenance POST, migration script, transaction seeding, or private305 app.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

DOMAIN = 'org.humanitylabs.wizard.mvp'
FROZEN = 'e4c2316351baa9fb0aa8ebd7c2de7f022f136d92'


def run(argv, *, timeout=60, check=True):
    return subprocess.run([str(x) for x in argv], check=check, capture_output=True,
                          text=True, timeout=timeout)


def read_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def process_rows():
    rows = []
    for line in run(['ps', '-axo', 'pid=,command=']).stdout.splitlines():
        pid, command = line.strip().split(None, 1)
        rows.append((int(pid), command))
    return rows


def app_processes(app):
    return [(pid, command) for pid, command in process_rows()
            if command.startswith(str(app) + '/')]


def prefs():
    return plistlib.loads(subprocess.check_output(['defaults', 'export', DOMAIN, '-']))


def http(path):
    # Read-only inspection: never manufacture a lease on an unprimed guest.
    request = urllib.request.Request('http://127.0.0.1:48023' + path,
                                     headers={'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, body = response.status, response.read(65536)
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read(65536)
    # Store only health/activity projections, not accounts, sessions or content.
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None
    return {'status': status, 'json': parsed, 'bodySHA256': hashlib.sha256(body).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--baseline-disk', type=Path, required=True)
    p.add_argument('--boot-dir', type=Path, required=True)
    p.add_argument('--old-app', type=Path, required=True)
    p.add_argument('--old-launch-app', type=Path, required=True)
    p.add_argument('--new-app', type=Path, required=True)
    p.add_argument('--quit-helper', type=Path, required=True)
    p.add_argument('--worker-lease', choices=['inherited'], required=True)
    a = p.parse_args()
    assert os.uname().sysname == 'Darwin', 'Mac-only diagnostic'
    for path in [a.root, a.baseline_disk, a.boot_dir, a.old_app, a.quit_helper]:
        assert path.resolve().is_relative_to('/Volumes/ThalesMedia'), path
    assert a.new_app.resolve().is_relative_to('/Applications') or a.new_app.resolve().is_relative_to('/Volumes/ThalesMedia')
    assert not a.root.exists(), 'Use a new evidence directory; never overwrite a run'
    assert a.baseline_disk.is_file() and a.quit_helper.is_file()
    assert a.old_launch_app.parent == Path('/Applications') and a.old_launch_app.suffix == '.app'
    assert not a.old_launch_app.exists(), 'Do not replace any installed app'
    for app, version in [(a.old_app, '0.6.1'), (a.new_app, '0.7.0')]:
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        assert info['CFBundleShortVersionString'] == version
        assert info['CFBundleIdentifier'] == DOMAIN
    release = read_json(a.new_app / 'Contents/Resources/wizard-release.json')
    assert release['releaseID'] == FROZEN and release['build'] == '306'
    assert not any('/Contents/MacOS/Wizard' in command for _, command in process_rows()), 'A Wizard app or Host is already running; do not touch shared preferences'
    assert not app_processes(a.new_app) and not app_processes(a.old_app), 'An app is already running'
    for port in [48000, 48023, 48030]:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    console = plistlib.loads(subprocess.check_output(['ioreg', '-n', 'Root', '-d1', '-a']))
    console = console if isinstance(console, dict) else console[0]
    assert not console.get('IOConsoleLocked') and not any(x.get('CGSSessionScreenIsLocked') for x in console.get('IOConsoleUsers', [])), 'Thales console locked'
    a.root.mkdir(parents=True)
    os.chmod(a.root, 0o700)
    data = a.root / 'data'
    files = a.root / 'Files'
    old_copy = a.old_launch_app
    evidence = {'schema': 1, 'source': FROZEN, 'phase': 'preflight',
                'purpose': 'unprimed direct replacement gap reproduction',
                'upgradeAccepted': False, 'private305Used': False,
                'manualMigrationUsed': False, 'transactionPrimed': False,
                'maxQAVMs': 1, 'memoryMiB': 4096, 'leaseMode': 'durable-worker-inherited'}
    def save():
        target = a.root / 'result.json'
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(evidence, indent=2) + '\n')
        tmp.replace(target)
    baseline_stat = (a.baseline_disk.stat().st_ino, a.baseline_disk.stat().st_size, a.baseline_disk.stat().st_mtime_ns)
    native_hashes = {str(app): sha(app / 'Contents/MacOS/Wizard') for app in [a.old_app, a.new_app]}
    before = prefs()
    (a.root / 'prefs-before.plist').write_bytes(plistlib.dumps(before))
    os.chmod(a.root / 'prefs-before.plist', 0o600)
    modified_prefs = False
    launched = []
    keepawake = None

    def stop(app):
        rows = app_processes(app)
        # Exact owned path + PID only; never broadcast a quit command.
        for host in [True, False]:
            for pid, command in rows:
                if ('/Wizard Host.app/' in command) == host:
                    run([a.quit_helper, pid], timeout=20)
            deadline = time.monotonic() + 100
            while any(('/Wizard Host.app/' in command) == host for _, command in app_processes(app)):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned process failed graceful stop; do not force it or restore defaults')
                time.sleep(.5)
        assert not app_processes(app)

    def start(app, label):
        assert not any('/Wizard Host.app/' in command for _, command in process_rows()), 'Unexpected Host appeared'
        launched.append(app)
        uid = str(os.getuid())
        run(['sudo', '-n', 'launchctl', 'asuser', uid, 'sudo', '-n', '-u', getpass.getuser(), 'open', '-n', '-g', '-j', app])
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            state = read_json(data / 'host-status.json')
            if state.get('state') == 'running':
                try:
                    health = http('/wizard/health')
                    if health['status'] == 200:
                        evidence[label] = {'host': state, 'health': health,
                                           'runtimeActivity': http('/wizard/v1/runtime/activity')}
                        save()
                        return
                except (OSError, ValueError):
                    pass
            time.sleep(1)
        raise TimeoutError(label + ': local ready timeout')

    try:
        keepawake = subprocess.Popen(['/usr/bin/caffeinate', '-d', '-i', '-u', '-t', '900'])
        (data / 'os/boot').mkdir(parents=True)
        files.mkdir()
        (files / 'preserve.txt').write_text('LEGACY061_DIRECT_REPLACEMENT_SENTINEL\n')
        selection = json.dumps({'path': str(files)})
        (data / 'files-folder.json').write_text(selection)
        run(['cp', '-c', a.baseline_disk, data / 'os/disk.img'], timeout=120)
        for name in ['vmlinux', 'initrd']:
            run(['cp', '-c', a.boot_dir / name, data / 'os/boot' / name])
        # Matches the existing baseline's boot contract, not an invented guest version.
        (data / 'os/manifest.json').write_text(json.dumps({'cmdline': 'console=hvc0 root=/dev/vda rw', 'memoryMiB': 4096}))
        run(['cp', '-cR', a.old_app, old_copy], timeout=120)
        overrides = {'DataHome': str(data), 'WizardKeyEnabled': False, 'VoiceKeysEnabled': False,
                     'backends': json.dumps([{'kind': 'thisMac', 'name': 'This Mac', 'url': ''}]).encode(),
                     'activeBackend': 0, 'SUEnableAutomaticChecks': False, 'SUAutomaticallyUpdate': False,
                     'QAHooks': False, 'QAWebStorage': False}
        (a.root / 'prefs-probe.plist').write_bytes(plistlib.dumps({**before, **overrides}))
        os.chmod(a.root / 'prefs-probe.plist', 0o600)
        modified_prefs = True
        run(['defaults', 'import', DOMAIN, a.root / 'prefs-probe.plist'])
        assert prefs()['DataHome'] == str(data)
        assert not (data / 'dev-shell').exists() and not (data / 'updates/transaction.json').exists()
        start(old_copy, 'original061')
        stop(old_copy)
        evidence['phase'] = 'original-stopped'; save()
        # Normal launch of exact public306 against the same original, unprimed disk.
        start(a.new_app, 'direct306')
        evidence['transactionAfterDirectReplacement'] = read_json(data / 'updates/transaction.json')
        evidence['maintenanceJournalAfterReplacement'] = read_json(data / 'updates/maintenance-lease.json')
        evidence['filesSelectionPreserved'] = (data / 'files-folder.json').read_text() == selection
        evidence['sharedSentinelPreserved'] = (files / 'preserve.txt').read_text() == 'LEGACY061_DIRECT_REPLACEMENT_SENTINEL\n'
        assert evidence['filesSelectionPreserved'] and evidence['sharedSentinelPreserved']
        assert not evidence['transactionAfterDirectReplacement'], 'Behavior changed: investigate rather than claim this old gap'
        assert evidence['direct306']['runtimeActivity']['status'] == 404, 'Baseline is not the expected unprimed guest'
        evidence['gapReproduced'] = True
        evidence['phase'] = 'legacy-bootstrap-blocker-reproduced'
    except Exception as error:
        evidence['phase'] = 'failed'
        evidence['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        cleanup_errors = []
        for app in reversed(launched):
            try:
                stop(app)
            except Exception as error:
                cleanup_errors.append(str(error))
        live = [(pid, command) for app in launched for pid, command in app_processes(app)]
        evidence['remainingOwned'] = live
        if modified_prefs and not live:
            current = prefs()
            for key in set(current) - set(before):
                run(['defaults', 'delete', DOMAIN, key])
            run(['defaults', 'import', DOMAIN, a.root / 'prefs-before.plist'])
            evidence['prefsRestored'] = prefs() == before
        evidence['originalBaselineUnchanged'] = baseline_stat == (a.baseline_disk.stat().st_ino, a.baseline_disk.stat().st_size, a.baseline_disk.stat().st_mtime_ns)
        evidence['originalNativeBytesUnchanged'] = all(sha(Path(app) / 'Contents/MacOS/Wizard') == digest for app, digest in native_hashes.items())
        if not live and old_copy.exists():
            assert sha(old_copy / 'Contents/MacOS/Wizard') == native_hashes[str(a.old_app)]
            shutil.rmtree(old_copy)
        evidence['owned061BundleRemoved'] = not old_copy.exists()
        if keepawake:
            keepawake.terminate()
            keepawake.wait(timeout=10)
        evidence['cleanupErrors'] = cleanup_errors
        save()
        assert not cleanup_errors and not live, 'Cleanup failed; retained exact ownership evidence'
        assert evidence.get('prefsRestored', not modified_prefs)
        assert evidence['originalBaselineUnchanged'] and evidence['originalNativeBytesUnchanged']
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
