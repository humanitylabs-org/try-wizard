#!/usr/bin/env python3
"""Bounded production voice component update, used by factory and stack upgrade.

The existing authenticated runtime BOM covers the package bytes. This installer
never loads/pulls/restarts an engine image. Rollback restores code and bindings
with the coordinator disabled, so an old writer cannot activate a downgrade.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

FILES = (
    'opt/wizard/bin/wizard-apps', 'opt/wizard/setup/server.py',
    'opt/wizard/voice/reconcile.py', 'opt/wizard/voice/install.py',
    'etc/systemd/system/wizard-voice.service',
)
BINDING = 'home/wizard/runtipi/user-config/wizardapps/transcriber/docker-compose.yml'
CONTRACT = 'opt/wizard/voice/selected-engine.json'
BACKUP = 'var/lib/wizard/patches/local-voice-v1'
FENCE = 'etc/systemd/system/wizard-voice.service.d/90-voice-rollback-inert.conf'
FENCE_BYTES = b'[Unit]\nConditionPathExists=/var/lib/wizard/voice-rollback-approved\n'


def check_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('Redirected voice update path refused')


def load_reconciler(payload):
    spec = importlib.util.spec_from_file_location('voice_update_reconciler', payload/'overlay/opt/wizard/voice/reconcile.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('Voice reconciler cannot be loaded')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def install(payload, root=Path('/'), run=subprocess.run):
    lock = root/'var/lib/wizard/voice-reconcile.lock'
    check_path(lock)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if root == Path('/'):
            os.fchown(fd, 1000, 1000)
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Local voice preparation is busy; retry the update after it finishes')
        return _install(payload, root, run)
    finally:
        os.close(fd)


def _install(payload, root, run):
    module = load_reconciler(payload)
    # Preflight all input/output members before making any code/binding changes.
    for rel in FILES:
        source = payload/'overlay'/rel
        check_path(source); check_path(root/rel)
        if not source.is_file(): raise RuntimeError('Incomplete voice package: ' + rel)
    selected = payload/'selected-engine.json'
    module.selection(selected)  # protected selection; root-owned parent chain
    check_path(root/BINDING); check_path(root/CONTRACT); check_path(root/BACKUP)
    check_path(root/FENCE)
    if (root/'var/lib/wizard/voice-rollback-approved').exists():
        raise RuntimeError('Unexpected rollback approval marker; refusing legacy writer admission')
    if (root/FENCE).exists() and (root/FENCE).read_bytes() != FENCE_BYTES:
        raise RuntimeError('Unknown voice rollback fence; review before updating')
    if not (root/BINDING).is_file(): raise RuntimeError('Missing installed security-selected voice binding')
    current = root/CONTRACT
    if current.exists() and current.read_bytes() != selected.read_bytes():
        raise RuntimeError('Voice image selection changed; separate selected-image upgrade required')
    # Validate/migrate a private copy first. Preserve real bytes until all
    # configuration validation has passed (including unknown security fields).
    backup = root/BACKUP
    backup.mkdir(parents=True, exist_ok=True, mode=0o700); backup.chmod(0o700)
    if (backup/'receipt.json').exists():
        receipt = json.loads((backup/'receipt.json').read_text())
        desired = {rel: hashlib.sha256((payload/'overlay'/rel).read_bytes()).hexdigest() for rel in FILES}
        if receipt.get('installed') != desired:
            raise RuntimeError('A different voice component transaction already exists')
        if all((root/rel).is_file() and hashlib.sha256((root/rel).read_bytes()).hexdigest() == sha for rel, sha in desired.items()) and current.read_bytes() == selected.read_bytes():
            return {'alreadyInstalled': True}
        raise RuntimeError('Previous voice transaction needs rollback before retrying')
    probe = backup/'binding-preflight.yml'
    module.atomic(probe, (root/BINDING).read_bytes(), 0o600)
    module.migrate_override(probe, json.loads(selected.read_text()))
    rendered = probe.read_bytes()
    probe.unlink()
    members = (*FILES, CONTRACT, BINDING)
    originals = {}
    for rel in members:
        path = root/rel
        originals[rel] = {'exists': path.exists(), 'mode': path.stat().st_mode & 0o777 if path.exists() else None,
                          'uid': path.stat().st_uid if path.exists() else None,
                          'gid': path.stat().st_gid if path.exists() else None}
        if path.exists():
            dest = backup/'original'/rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.read_bytes() != path.read_bytes():
                raise RuntimeError('Voice backup collision; refusing overwrite')
            if not dest.exists(): shutil.copy2(path, dest)
    module.atomic(backup/'originals.json', json.dumps(originals, sort_keys=True).encode(), 0o600)
    run(['systemctl', 'stop', 'wizard-voice'], check=True)
    run(['systemctl', 'disable', 'wizard-voice'], check=True)
    try:
        for rel in FILES:
            path = root/rel; path.parent.mkdir(parents=True, exist_ok=True)
            source = payload/'overlay'/rel
            module.atomic(path, source.read_bytes(), 0o755 if source.stat().st_mode & 0o111 else 0o644)
        module.atomic(current, selected.read_bytes())
        module.atomic(root/BINDING, rendered)
        if root == Path('/'):
            # WAM owns user-config, never recursive chmod/chown or app data.
            os.chown(root/BINDING, 1000, 1000)
            lock = root/'var/lib/wizard/voice-reconcile.lock'
            if not lock.exists():
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd); os.chown(lock, 1000, 1000)
        (root/FENCE).unlink(missing_ok=True)
        run(['systemctl', 'daemon-reload'], check=True)
        run(['systemctl', 'enable', 'wizard-voice'], check=True)
        run(['systemctl', 'try-restart', 'wizard-setup'], check=True)
        receipt = {'schema': 1, 'installed': {rel: hashlib.sha256((root/rel).read_bytes()).hexdigest() for rel in FILES},
                   'contractSha256': hashlib.sha256(current.read_bytes()).hexdigest(),
                   'bindingSha256': hashlib.sha256((root/BINDING).read_bytes()).hexdigest(),
                   'imageStoreMutated': False, 'engineLifecycleMutated': False}
        module.atomic(backup/'receipt.json', json.dumps(receipt, sort_keys=True).encode(), 0o600)
        return receipt
    except Exception:
        _rollback(root, run)
        raise


def rollback(root=Path('/'), run=subprocess.run):
    lock = root/'var/lib/wizard/voice-reconcile.lock'; check_path(lock)
    fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Local voice is busy; rollback refused')
        return _rollback(root, run)
    finally: os.close(fd)


def _rollback(root, run):
    backup = root/BACKUP; check_path(backup)
    originals = json.loads((backup/'originals.json').read_text())
    if set(originals) != {*FILES, CONTRACT, BINDING}: raise RuntimeError('Invalid voice rollback inventory')
    run(['systemctl', 'stop', 'wizard-voice'], check=True)
    run(['systemctl', 'disable', 'wizard-voice'], check=True)
    for rel, meta in originals.items():
        target = root/rel; check_path(target)
        if meta['exists']:
            source = backup/'original'/rel; check_path(source)
            shutil.copy2(source, target); target.chmod(meta['mode'])
            if root == Path('/'): os.chown(target, meta['uid'], meta['gid'])
        else: target.unlink(missing_ok=True)
    fence = root/FENCE; check_path(fence); fence.parent.mkdir(parents=True, exist_ok=True)
    # Disable alone does NOT block manual Retry starts. An explicit condition
    # keeps restored legacy code inert, including after boot and Retry.
    with fence.open('wb') as stream:
        stream.write(FENCE_BYTES); stream.flush(); os.fsync(stream.fileno())
    fence.chmod(0o644)
    run(['systemctl', 'daemon-reload'], check=True)
    run(['systemctl', 'try-restart', 'wizard-setup'], check=True)
    if (backup/'receipt.json').exists():
        os.replace(backup/'receipt.json', backup/'rolled-back.json')
    # No start/enable on rollback: restored legacy coordinator stays inert.
    return {'rolledBack': True, 'coordinatorDisabled': True, 'imageStoreMutated': False}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('payload', type=Path, nargs='?')
    parser.add_argument('--apply', action='store_true'); parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0: raise SystemExit('Voice component update requires root')
    if args.rollback: result = rollback()
    elif args.apply and args.payload: result = install(args.payload.resolve())
    else: raise SystemExit('Use PAYLOAD --apply or --rollback; authenticated package required')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
