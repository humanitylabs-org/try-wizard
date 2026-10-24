#!/usr/bin/env python3
"""Source-only matrix runner. Plan anywhere; execute later on an isolated Thales QA account.

Execution requires an operator-populated fixture spec, signed DMGs and retained
rig drivers. Does not build, publish, create VMs outside the supplied QA data home,
or claim that an unexecuted row passed. See update-arch-v2-matrix.md.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

MAC = Path(__file__).resolve().parents[1]
LOCK = '/Volumes/ThalesMedia/AndroidBuilds/worker.lock'


def cases(published):
    rows = [{'id': f'fresh-{app}-{image}', 'kind': 'fresh', 'app': app, 'image': image}
            for app in ('N-1', 'N') for image in ('N-1', 'N')]
    rows += [{'id': 'published-' + p['id'], 'kind': 'published', 'fixture': p} for p in published]
    rows += [{'id': kind, 'kind': kind, 'app': 'N', 'image': 'N-1'}
             for kind in ('aged-disk', 'interrupt-mid-apply', 'rollback')]
    return rows


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def verify(row, spec, evidence):
    data = Path(spec['dataHome'])
    status = read(data / 'host-status.json')
    if status.get('state') != 'running':
        raise RuntimeError('Real normal VM not running after case')
    journal_path = data / 'updates/transaction.json'
    journal = read(journal_path) if journal_path.exists() else {}
    if row.get('app') == 'N' and row['kind'] not in ('interrupt-mid-apply', 'rollback'):
        receipt = read(data / 'updates/guest-receipt.json')
        if receipt.get('systemOwner') != 'host-payload' or not receipt.get('payloadID'):
            raise RuntimeError('Missing host-owned payload receipt')
        if journal.get('phase') != 'guest-activated':
            raise RuntimeError('Payload not activated')
        if row['kind'] == 'aged-disk':
            health = read(data / 'updates/apps-health.json')
            if not journal.get('appsBefore') or health.get('nonce') != journal.get('nonce') or health.get('ok') is not True:
                raise RuntimeError('Aged app inventory / resume health not proved')
    if row['kind'] in ('interrupt-mid-apply', 'rollback'):
        interrupted = read(evidence / 'interrupted.json')
        if interrupted.get('phase') != 'guest-activating' or not interrupted.get('nonce'):
            raise RuntimeError('Fault was not observed during actual payload apply')
        if journal.get('phase') != 'guest-rolled-back':
            raise RuntimeError('Interrupted payload was not rolled back')
        expected = (evidence / 'before-disk.sha256').read_text().strip()
        # Booting a restored disk changes logs/journals. The fault driver must
        # APFS-clone the stopped restored inode before normal boot, then retain
        # that immutable witness and its inode binding for independent hashing.
        proof = read(evidence / 'restored-proof.json')
        st = (data / 'os/disk.img').stat()
        if proof.get('diskIdentity') != f'{st.st_dev}:{st.st_ino}':
            raise RuntimeError('Rollback witness is not bound to current disk inode')
        if len(expected) != 64 or sha(evidence / 'restored-stopped.img') != expected:
            raise RuntimeError('Stopped restored disk does not equal pre-apply checkpoint')
    return {'normalHost': status, 'journal': journal}


def execute(spec, rows, root):
    if platform.system() != 'Darwin':
        raise RuntimeError('Execution is Thales/macOS only; use --plan on Linux')
    if os.environ.get('USER') != spec['qaUser'] or spec['qaUser'] in ('root', 'telos', 'james'):
        raise RuntimeError('Use the explicit isolated macOS QA account')
    work = Path(spec['workRoot']).resolve()
    if not work.is_relative_to(Path('/Volumes/ThalesMedia')):
        raise RuntimeError('All matrix work belongs on the external work disk')
    data = Path(spec['dataHome']).resolve()
    if not data.is_relative_to(work) or not root.resolve().is_relative_to(work):
        raise RuntimeError('QA data and immutable evidence must be under workRoot')
    support = Path.home() / 'Library/Application Support/Wizard'
    if support.resolve() != data:
        raise RuntimeError('QA account Wizard support directory must point at dataHome')
    if (work / '.wizard-update-matrix').read_text().strip() != spec['qaUser']:
        raise RuntimeError('Missing explicit disposable-rig marker')
    # lockf's POSIX lease is inherited by the command tree, not flock.
    with open(LOCK, 'a') as lock:
        try:
            fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.lockf(lock, fcntl.LOCK_UN)
            raise RuntimeError('Worker lock is not held; wrap the whole invocation in lockf -k')
    revision = subprocess.check_output(['git', '-C', str(MAC), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != spec['source']:
        raise RuntimeError('Matrix source differs from immutable fixture spec')
    root.mkdir(parents=True, exist_ok=False)
    result = {'source': revision, 'published': False, 'rows': [], 'complete': False}
    def save():
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    save()
    try:
        for row in rows:
            ev = root / row['id']; ev.mkdir()
            env = dict(os.environ, WIZARD_WORK_ROOT=str(work), PYTHONDONTWRITEBYTECODE='1')
            if row['kind'] in ('fresh', 'published'):
                fixture = row.get('fixture')
                if fixture:
                    dmg, archive, feed = fixture['dmg'], fixture['archive'], fixture['feedURL']
                else:
                    dmg = spec['apps'][row['app']]['dmg']
                    image = spec['images'][row['image']]
                    archive, feed = image['archive'], image['feedURL']
                env['FEED_URL'] = feed
                argv = ['bash', str(MAC / 'qa-fresh.sh'), dmg, archive, str(ev)]
            else:
                # The retained/fault rig is fixture-specific. Execute its real argv,
                # then independently read the exact disk/journal/health targets.
                argv = spec['retainedCommands'][row['id']] + ['--evidence', str(ev)]
            (ev / 'invocation.json').write_text(json.dumps({'row': row, 'argv': argv}, indent=2) + '\n')
            with (ev / 'driver.log').open('w') as log:
                subprocess.run(argv, check=True, timeout=spec.get('timeoutSeconds', 2400), env=env, stdout=log, stderr=subprocess.STDOUT)
            observed = verify(row, spec, ev)
            result['rows'].append({'id': row['id'], 'passed': True, 'logSHA256': sha(ev / 'driver.log'), 'observed': observed})
            save()
        result['complete'] = len(result['rows']) == len(rows)
    except BaseException as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--locked', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.spec:
        if not args.plan:
            parser.error('--spec required to execute')
        print(json.dumps(cases([{'id': '0.7.0'}, {'id': '0.7.1'}]), indent=2)); return
    spec = read(args.spec)
    if len(spec['publishedDMGs']) < 2:
        parser.error('Include every published legacy DMG/feed, at least 0.7.0 and 0.7.1')
    rows = cases(spec['publishedDMGs'])
    if len({r['id'] for r in rows}) != len(rows):
        parser.error('Duplicate matrix row')
    if not args.execute:
        print(json.dumps(rows, indent=2)); return
    if platform.system() != 'Darwin':
        parser.error('Execution is Thales/macOS only')
    if args.locked != os.environ.get('WIZARD_MATRIX_LOCK_TOKEN') or not args.locked:
        token = uuid.uuid4().hex
        env = dict(os.environ, WIZARD_MATRIX_LOCK_TOKEN=token)
        # One lock covers the entire suite. No VM/build is launched while queued.
        subprocess.run(['/usr/bin/lockf', '-k', LOCK, sys.executable, str(Path(__file__).resolve()),
                        '--spec', str(args.spec.resolve()), '--execute', '--locked', token], env=env, check=True)
        return
    execute(spec, rows, Path(spec['evidenceRoot']))


if __name__ == '__main__':
    main()
