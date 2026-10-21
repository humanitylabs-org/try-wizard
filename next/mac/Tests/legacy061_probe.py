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
import re
import shutil
import signal
import socket
import sys
import subprocess
import time
import urllib.error
import urllib.request

WORK_ROOT = Path(os.environ.get("WIZARD_WORK_ROOT") or Path(os.environ.get("TMPDIR") or "/tmp") / "wizard-work").expanduser().resolve()
WORK_ROOT.mkdir(parents=True, exist_ok=True)

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


def wizard_process_identity(pid, command):
    """Read the executable's own bundle, not a basename or the outer Host app.

    Only the separately verified pre-MVP product is a known disjoint identity.
    Unknown/unreadable identities fail closed rather than evade the MVP guard.
    """
    match = re.match(r'^(/.+)/Contents/MacOS/(Wizard Host|Wizard)(?:\s|$)', command)
    if not match: raise RuntimeError('Unknown Wizard executable identity: '+str(pid))
    bundle, executable = Path(match[1]), match[2]
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    identity = info.get('CFBundleIdentifier')
    if info.get('CFBundleExecutable') != executable:
        raise RuntimeError('Wizard executable/plist identity mismatch: '+str(pid))
    if identity in (DOMAIN, DOMAIN+'.host'):
        raise RuntimeError('Competing MVP app/Host is running: '+str(pid))
    if identity not in ('org.humanitylabs.wizard', 'org.humanitylabs.wizard.host'):
        raise RuntimeError('Unknown Wizard bundle identity: '+str(pid))
    outer = next((p for p in reversed(bundle.parents) if p.suffix == '.app'), bundle)
    outer_info = plistlib.loads((outer/'Contents/Info.plist').read_bytes())
    if outer_info.get('CFBundleIdentifier') != 'org.humanitylabs.wizard':
        raise RuntimeError('Unknown outer Wizard bundle identity: '+str(pid))
    return {'pid':pid, 'bundle':str(bundle), 'bundleID':identity,
            'outerBundleID':outer_info['CFBundleIdentifier'], 'version':info.get('CFBundleShortVersionString'),
            'preferencesDomain':'org.humanitylabs.wizard',
            # Verified pre-MVP Shared.swift uses this fixed applicationSupport root,
            # not the MVP DataHome preference (recorded in parent coordination).
            'supportDir':str(Path.home()/'Library/Application Support/Wizard')}


def assert_no_competing_wizard():
    disjoint = []
    for pid, command in process_rows():
        if '/Contents/MacOS/Wizard' not in command: continue
        record = wizard_process_identity(pid, command)
        listeners = run(['lsof','-nP','-a','-p',str(pid),'-iTCP','-sTCP:LISTEN','-Fn'], check=False)
        if listeners.returncode not in (0, 1): raise RuntimeError('Cannot inspect Wizard listeners')
        names = [line[1:] for line in listeners.stdout.splitlines() if line.startswith('n')]
        ports = sorted({int(name.rsplit(':',1)[1]) for name in names})
        if not set(ports).issubset({47823,47830}): raise RuntimeError('Disjoint Wizard has unexpected listening ports')
        record.update(listeningPorts=ports, untouched=True)
        disjoint.append(record)
    return disjoint


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


def stopped_content(disk, scratch):
    """Read the stopped clone through a read-only ext4 reader; retain hashes only.
    Never mount/boot the baseline, and never execute anything from the guest.
    """
    import sqlite3
    scratch.mkdir(mode=0o700)
    base=['/opt/homebrew/bin/docker','--context','colima-wb','run','--rm','--network','none','--read-only',
          '-v',str(disk)+':/disk:ro','--entrypoint','/usr/sbin/debugfs','wizard-os-base:0.3.0']
    def read(command):
        return subprocess.run(base+['-R',command,'/disk'],check=True,capture_output=True,timeout=40).stdout
    out={'databases':{}}
    guest='/home/wizard/runtipi/app-data/wizardapps/hermes-agent/data/'
    try:
        for name in ('state.db','response_store.db','shared-state.db','kanban.db','runs_idempotency.db'):
            data=read('cat '+guest+name)
            if not data: continue
            path=scratch/name;path.write_bytes(data);os.chmod(path,0o600)
            wal=read('cat '+guest+name+'-wal')
            if wal: path.with_name(name+'-wal').write_bytes(wal)
            with sqlite3.connect(path) as db:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('sessions','messages'):
                    if table in tables:
                        rows=list(db.execute('SELECT * FROM '+table+' ORDER BY id'))
                        out['databases'][name+'/'+table]={'count':len(rows),'rowsSHA256':hashlib.sha256(json.dumps(rows,default=lambda b:b.hex(),sort_keys=True).encode()).hexdigest()}
        assert out['databases']['state.db/messages']['count'] > 0, 'Original used-disk chats missing'
        listing=read('ls -p /home/wizard/runtipi/app-data/wizardapps').decode()
        out['installedAppDataDirectories']=sorted(line.split('/')[5] for line in listing.splitlines() if len(line.split('/'))>5 and line.split('/')[5] not in ('.','..'))
        return out
    finally: shutil.rmtree(scratch)


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
    p.add_argument('--candidate-source', default='', help='build307 production candidate; empty retains the306 diagnostic')
    a = p.parse_args()
    assert os.uname().sysname == 'Darwin', 'Mac-only diagnostic'
    for path in [a.root, a.baseline_disk, a.boot_dir, a.old_app, a.quit_helper]:
        assert path.resolve().is_relative_to(WORK_ROOT), path
    assert a.new_app.resolve().is_relative_to('/Applications') or a.new_app.resolve().is_relative_to(WORK_ROOT)
    assert not a.root.exists(), 'Use a new evidence directory; never overwrite a run'
    assert a.baseline_disk.is_file() and a.quit_helper.is_file()
    assert a.old_launch_app.parent == Path('/Applications') and a.old_launch_app.suffix == '.app'
    assert not a.old_launch_app.exists(), 'Do not replace any installed app'
    for app, version in [(a.old_app, '0.6.1'), (a.new_app, '0.7.0')]:
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        assert info['CFBundleShortVersionString'] == version
        assert info['CFBundleIdentifier'] == DOMAIN
    release = read_json(a.new_app / 'Contents/Resources/wizard-release.json')
    assert release['releaseID'] == (a.candidate_source or FROZEN) and release['build'] == ('307' if a.candidate_source else '306')
    disjoint_processes = assert_no_competing_wizard()
    assert not app_processes(a.new_app) and not app_processes(a.old_app), 'An app is already running'
    for port in [48000, 48023, 48030]:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    console = plistlib.loads(subprocess.check_output(['ioreg', '-n', 'Root', '-d1', '-a']))
    console = console if isinstance(console, dict) else console[0]
    # Lock protects the human desktop, not the isolated background VM. Record it;
    # use already-authorized direct Accessibility instead of Apple Events.
    console_locked = bool(console.get('IOConsoleLocked') or any(x.get('CGSSessionScreenIsLocked') for x in console.get('IOConsoleUsers', [])))
    a.root.mkdir(parents=True)
    os.chmod(a.root, 0o700)
    data = a.root / 'data'
    files = a.root / 'Files'
    old_copy = a.old_launch_app
    evidence = {'schema': 1, 'source': a.candidate_source or FROZEN, 'phase': 'preflight',
                'purpose': 'native consented cold candidate' if a.candidate_source else 'unprimed direct replacement gap reproduction',
                'upgradeAccepted': False, 'private305Used': False,
                'manualMigrationUsed': False, 'transactionPrimed': False,
                'maxQAVMs': 1, 'memoryMiB': 4096, 'leaseMode': 'durable-worker-inherited',
                'disjointProcesses': disjoint_processes, 'selectedPorts': [48000,48023,48030],
                'selectedPreferencesDomain':DOMAIN, 'selectedDataHome':str(data),
                'consoleLockedAtStart':console_locked, 'unlockAttempted':False,
                'consentTransport':'direct-accessibility-exact-owned-pid'}
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
    def interrupted(signum, _frame):
        raise TimeoutError('Worker interrupted diagnostic with signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)

    def stop(app):
        rows = app_processes(app)
        # Exact owned path + PID only; never broadcast a quit command.
        for host in [True, False]:
            for pid, command in rows:
                if ('/Wizard Host.app/' in command) == host:
                    quit_result = run([a.quit_helper, pid], timeout=20, check=False)
                    if quit_result.returncode and not host:
                        # A pre-VM GUI stuck in file access has no guest to stop.
                        # Never force a Host or an app with any live owned Host.
                        current = app_processes(app)
                        if not any(p == pid for p, _ in current):
                            continue
                        exact = str(app / 'Contents/MacOS/Wizard')
                        if any('/Wizard Host.app/' in cmd for _, cmd in current):
                            raise RuntimeError('Owned Host still running; force cleanup refused')
                        actual = subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True).strip()
                        fds = subprocess.run(['lsof','-p',str(pid),'-Fn'],capture_output=True,text=True)
                        assert actual == exact and fds.returncode == 0 and 'disk.img' not in fds.stdout
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(1)
                        if any(p == pid for p,_ in app_processes(app)):
                            os.kill(pid, signal.SIGKILL)
                        evidence.setdefault('preVMAppCleanup', []).append(pid)
                    elif quit_result.returncode:
                        raise RuntimeError('Owned Host refused graceful shutdown')
            deadline = time.monotonic() + 100
            while any(('/Wizard Host.app/' in command) == host for _, command in app_processes(app)):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned process failed graceful stop; do not force it or restore defaults')
                time.sleep(.5)
        assert not app_processes(app)

    def start(app, label):
        evidence.setdefault("prelaunchDisjointProcesses", []).append(assert_no_competing_wizard())
        launched.append(app)
        uid = str(os.getuid())
        # Keep the authorized SSH/worker responsibility chain. LaunchServices
        # detaches it and can block the old app on removable-volume consent.
        # This executes the unchanged signed app, not a substitute migration.
        log = (a.root / (label + '-native.log')).open('w')
        child = subprocess.Popen(['sudo', '-n', 'launchctl', 'asuser', uid,
                                  'sudo', '-n', '-u', getpass.getuser(),
                                  str(app / 'Contents/MacOS/Wizard')], stdout=log, stderr=subprocess.STDOUT)
        log.close()
        evidence.setdefault('directLaunches', []).append({'label':label,'pid':child.pid})
        save()
        deadline = time.monotonic() + (1800 if a.candidate_source and app == a.new_app else 240)
        consent_clicked = False
        while time.monotonic() < deadline:
            if a.candidate_source and app == a.new_app:
                ui = read_json(data/'updates/ui.json')
                if ui.get('phase') == 'failed': raise RuntimeError('Candidate refused: '+ui.get('message',''))
                if not consent_clicked and not (data/'updates/transaction.json').exists():
                    rows = [(pid,cmd) for pid,cmd in app_processes(app) if '/Wizard Host.app/' not in cmd]
                    if len(rows)==1:
                        clicked=run([sys.executable,Path(__file__).with_name('ax_press_button.py'),str(rows[0][0]),'Upgrade existing Wizard'],check=False,timeout=10)
                        if clicked.returncode==0:
                            consent_clicked=True; evidence.setdefault('nativeConsentClicks',[]).append(label); save()
            state = read_json(data / 'host-status.json')
            if state.get('state') == 'running':
                try:
                    health = http('/wizard/health')
                    completed = not a.candidate_source or app != a.new_app or (data/'updates/legacy-complete.json').exists()
                    if health['status'] == 200 and completed:
                        evidence[label] = {'host': state, 'health': health,
                                           'runtimeActivity': http('/wizard/v1/runtime/activity')}
                        save()
                        return
                except (OSError, ValueError):
                    pass
            time.sleep(1)
        raise TimeoutError(label + ': local ready timeout')

    try:
        keepawake = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-t', '1800'])
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
        if a.candidate_source: evidence['preservationBefore'] = stopped_content(data/'os/disk.img', a.root/'before')
        # No transaction priming: the real app asks consent and performs the bootstrap.
        start(a.new_app, 'candidate307' if a.candidate_source else 'direct306')
        evidence['transactionAfterDirectReplacement'] = read_json(data / 'updates/transaction.json')
        evidence['maintenanceJournalAfterReplacement'] = read_json(data / 'updates/maintenance-lease.json')
        evidence['filesSelectionPreserved'] = (data / 'files-folder.json').read_text() == selection
        evidence['sharedSentinelPreserved'] = (files / 'preserve.txt').read_text() == 'LEGACY061_DIRECT_REPLACEMENT_SENTINEL\n'
        assert evidence['filesSelectionPreserved'] and evidence['sharedSentinelPreserved']
        if a.candidate_source:
            receipt=read_json(data/'updates/guest-receipt.json');witness=receipt.get('cold_bootstrap',{})
            assert witness.get('noOldEngine') and witness.get('forbiddenStartDenied') and witness.get('oldImageRecreationDeniedAfterMigration')
            assert witness.get('executionFenceHeldAfterCommit')
            assert {'create','start','exec'}.issubset(witness.get('postCommitDeniedRoutes', []))
            assert receipt['permanent_identity_credentials_preserved'] and receipt['configured_model_preserved']
            assert evidence['nativeConsentClicks']==['candidate307']
            evidence['coldWitness']=witness; evidence['candidateTested']=True
            stop(a.new_app)
            evidence['preservationAfter']=stopped_content(data/'os/disk.img',a.root/'after')
            assert evidence['preservationBefore']==evidence['preservationAfter'], 'Stored chats/apps changed'
            before_journal=sha(data/'updates/transaction.json')
            start(a.new_app,'repeat307')
            assert before_journal==sha(data/'updates/transaction.json')
            assert evidence['nativeConsentClicks']==['candidate307']
            evidence['repeatLaunchNoOp']=True;evidence['successPathAccepted']=True
            evidence['phase']='cold-candidate-success-path-passed-not-full-release-acceptance'
        else:
            assert not evidence['transactionAfterDirectReplacement'], 'Behavior changed: investigate rather than claim this old gap'
            assert evidence['direct306']['runtimeActivity']['status'] == 404, 'Baseline is not the expected unprimed guest'
            evidence['gapReproduced'] = True
            evidence['phase'] = 'legacy-bootstrap-blocker-reproduced'
    except Exception as error:
        evidence['phase'] = 'failed'
        evidence['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        # One termination request enters bounded cleanup; a repeated request must
        # not interrupt graceful VZ stop halfway through preference restoration.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
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
        final_console = plistlib.loads(subprocess.check_output(['ioreg','-n','Root','-d1','-a']))
        final_console = final_console if isinstance(final_console,dict) else final_console[0]
        evidence['consoleLockedAtEnd'] = bool(final_console.get('IOConsoleLocked') or any(x.get('CGSSessionScreenIsLocked') for x in final_console.get('IOConsoleUsers', [])))
        evidence['cleanupErrors'] = cleanup_errors
        save()
        assert not cleanup_errors and not live, 'Cleanup failed; retained exact ownership evidence'
        assert evidence.get('prefsRestored', not modified_prefs)
        assert evidence['originalBaselineUnchanged'] and evidence['originalNativeBytesUnchanged']
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
