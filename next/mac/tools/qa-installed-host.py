#!/usr/bin/env python3
"""Bounded installed-App -> real embedded Host -> VM smoke test (macOS only).

Caller must hold the shared POSIX worker.lock for the entire run. Does not
install an app, reset privacy, kill a VM, or treat launch admission as success.
"""
import argparse
import json
import os
import pathlib
import plistlib
import re
import signal
import subprocess
import time
from native_qa_launch import APP_ID, launch_installed


def run(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, timeout=kwargs.pop('timeout', 20), **kwargs)


def preferences():
    return plistlib.loads(subprocess.check_output(['defaults', 'export', APP_ID, '-']))


def owned_processes(app):
    result = []
    for line in subprocess.check_output(['ps', '-axo', 'pid,ppid,args'], text=True).splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) == 3 and fields[2].startswith(str(app / 'Contents/')):
            result.append({'pid': int(fields[0]), 'command': fields[2]})
    return result


def assert_no_other_mvp():
    for line in subprocess.check_output(['ps', '-axo', 'args'], text=True).splitlines():
        match = re.match(r'^(/.*?\.app)/Contents/MacOS/Wizard(?: Host)?(?:$| )', line)
        if not match:
            continue
        info = pathlib.Path(match.group(1)) / 'Contents/Info.plist'
        if info.is_file() and plistlib.loads(info.read_bytes()).get('CFBundleIdentifier') in (APP_ID, APP_ID + '.host'):
            raise RuntimeError('Another MVP App/Host is live; preserve its owner')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=pathlib.Path)
    parser.add_argument('--data-home', required=True, type=pathlib.Path)
    parser.add_argument('--evidence', required=True, type=pathlib.Path)
    parser.add_argument('--notify', required=True, type=pathlib.Path)
    args = parser.parse_args()
    app, data, evidence = args.app, args.data_home, args.evidence
    external = pathlib.Path('/Volumes')
    for p in (data, evidence):
        if external not in p.resolve().parents:
            raise ValueError('All work data and evidence must be on the external volume')
    assert_no_other_mvp()
    for port in (48023, 48030):
        if subprocess.run(['lsof', '-nP', '-iTCP:' + str(port), '-sTCP:LISTEN'], capture_output=True).stdout:
            raise RuntimeError('Required VM port is owned by another job')
    evidence.mkdir(parents=True, exist_ok=False)
    if not (data / 'os/disk.img').is_file():
        raise ValueError('Provide an already prepared, stopped, owned QA disk')
    status = data / 'host-status.json'
    if status.exists():
        old = json.loads(status.read_text())
        if subprocess.run(['kill', '-0', str(old.get('pid', 0))], capture_output=True).returncode == 0:
            raise RuntimeError('DataHome may be live; refusing stale-status removal')
        status.unlink()
    before = preferences()
    backup = evidence / 'prefs-before.plist'
    backup.write_bytes(plistlib.dumps(before)); os.chmod(backup, 0o600)
    selected = dict(before)
    selected.update(DataHome=str(data), QAHooks=True, QAWebStorage=True,
                    activeBackend=0, SUEnableAutomaticChecks=False,
                    backends=json.dumps([{'kind': 'thisMac', 'name': 'Owned Host probe',
                                         'url': 'http://127.0.0.1:48030/'}]).encode())
    owned = evidence / 'prefs-owned.plist'
    owned.write_bytes(plistlib.dumps(selected)); os.chmod(owned, 0o600)
    run(['defaults', 'import', APP_ID, owned])
    receipt = {'launch': 'LaunchServices background-first', 'dataHome': str(data),
               'vmRunning': False, 'bothNativeBridgesHealthy': False}
    try:
        launch_installed(app)
        end = time.monotonic() + 45
        while time.monotonic() < end:
            if status.exists():
                hs = json.loads(status.read_text()); receipt['hostStatus'] = hs
                expected = str(app / 'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host') + ' --wizard-data-home ' + str(data)
                rows = owned_processes(app)
                if hs.get('dataHome') == str(data) and hs.get('state') == 'running' and any(r['pid'] == hs.get('pid') and r['command'] == expected for r in rows):
                    receipt['vmRunning'] = True; break
            time.sleep(.5)
        if not receipt['vmRunning']:
            raise RuntimeError('Real Host did not reach running in 45 seconds; inspect samples, not another blind wait')
        import urllib.request
        end = time.monotonic() + 120
        while time.monotonic() < end:
            try:
                for url in ('http://127.0.0.1:48030/healthz', 'http://127.0.0.1:48023/wizard/health'):
                    with urllib.request.urlopen(url, timeout=2) as r:
                        if r.status != 200: raise RuntimeError('Native bridge not ready')
                receipt['bothNativeBridgesHealthy'] = True; break
            except (OSError, RuntimeError): time.sleep(1)
        if not receipt['bothNativeBridgesHealthy']:
            raise RuntimeError('VM running but native bridges are not healthy')
    finally:
        rows = owned_processes(app)
        receipt['processes'] = rows
        for row in rows:
            sample = evidence / (str(row['pid']) + '.sample.txt')
            subprocess.run(['sample', str(row['pid']), '1', '1', '-file', str(sample)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        (evidence / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        run([args.notify, 'update-quit'], stdout=subprocess.DEVNULL)
        run([args.notify, '--host', 'quit'], stdout=subprocess.DEVNULL)
        # Only the proved initializer stall is eligible for TERM. A VM is not.
        for row in owned_processes(app):
            sample = evidence / (str(row['pid']) + '.sample.txt')
            text = sample.read_text() if sample.exists() else ''
            host = str(app / 'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host')
            if row['command'] == host + ' --wizard-data-home ' + str(data) and not status.exists() and 'HostDelegate.applicationDidFinishLaunching' in text and 'mkdirat' in text and 'VZVirtualMachine' not in text:
                os.kill(row['pid'], signal.SIGTERM)
        end = time.monotonic() + 105
        while owned_processes(app) and time.monotonic() < end: time.sleep(.5)
        remaining = owned_processes(app)
        if remaining:
            raise RuntimeError('Owned process remains; retain prefs/evidence and acquire a cleanup lease')
        current = preferences()
        changed = {k for k in current.keys() | selected.keys() if current.get(k) != selected.get(k)}
        if changed - {'SULastCheckTime', 'SUUpdateGroupIdentifier'}:
            raise RuntimeError('Unknown preference owner changes; preserve current values: ' + ', '.join(sorted(changed)))
        run(['defaults', 'delete', APP_ID]); run(['defaults', 'import', APP_ID, backup])
        if preferences() != before: raise RuntimeError('Preference semantic readback failed')
        (evidence / 'cleanup.json').write_text(json.dumps({'prefsSemanticReadbackExactlyRestored': True,
                                                          'ownedProcessesRemaining': remaining}) + '\n')
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
