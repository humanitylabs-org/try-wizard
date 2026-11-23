#!/usr/bin/env python3
"""Install a code-only guest update inside an existing WizardOS guest on a Mac (try-wizard#123).

upgrade-mvp-stack.py (the fixed command the Host runs, next/mac/Shared/GuestPatchCommand.swift) hands a payload whose
runtime-bom.json says "kind": "code-only" to this file. It installs only this repo's guest files for the setup page
and the Mac window door (next/guest/build-code-payload.py), and never touches images, the agent, its config, accounts
or chats. The app copied the stopped disk before this runs and puts it back if this fails, so every check fails
closed. After it succeeds the VM restarts normally, which starts every installed file.

The receipt (applied.json) has the fields the Host's fixed check asserts: SOUL.md, .env and auth.json unchanged.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

PATCH = 'mac-stack-v1'
# The only places a code-only payload may write (relative to the guest's /).
ALLOWED = ('opt/wizard/', 'etc/systemd/system/wizard-', 'etc/systemd/resolved.conf.d/50-wizard-dns.conf')
UNITS = 'etc/systemd/system/'
DNS = 'etc/systemd/resolved.conf.d/50-wizard-dns.conf'
WINDOW_DOOR = ('opt/wizard/local-proxy.conf', 'opt/wizard/local-proxy-owner.inc', 'opt/wizard/bin/wizard-local-routes')
HERMES_DATA = 'home/wizard/runtipi/app-data/wizardapps/hermes-agent/data'


def _sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _guard():
    spec = importlib.util.spec_from_file_location('stack_preservation', Path(__file__).with_name('stack-preservation.py'))
    if spec is None or spec.loader is None:
        raise SystemExit('Missing preservation helper')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(payload):
    """The payload is exactly its BOM: every file listed, every listed file present and matching, nothing else."""
    payload = Path(payload)
    bom = json.loads((payload / 'runtime-bom.json').read_text())
    if bom.get('schema') != 1 or bom.get('kind') != 'code-only':
        raise SystemExit('Not a code-only guest update')
    files = bom.get('files')
    if not isinstance(files, dict) or not files:
        raise SystemExit('Empty code-only guest update')
    for relative, expected in files.items():
        parts = Path(relative).parts
        if Path(relative).is_absolute() or '..' in parts:
            raise SystemExit('Unsafe BOM member: ' + relative)
        if relative.startswith('overlay/'):
            if not relative[len('overlay/'):].startswith(ALLOWED):
                raise SystemExit('Code-only update may not write ' + relative[len('overlay'):])
        elif not relative.startswith('source/next/guest/'):
            raise SystemExit('Unknown BOM member: ' + relative)
        p = payload / relative
        if p.is_symlink() or not p.is_file():
            raise SystemExit('Missing or unsafe payload file: ' + relative)
        if _sha(p) != expected:
            raise SystemExit('BOM file mismatch: ' + relative)
    present = {str(p.relative_to(payload)) for p in payload.rglob('*') if p.is_file() or p.is_symlink()}
    present -= {'runtime-bom.json'}
    present = {p for p in present if '__pycache__' not in Path(p).parts}
    extra = sorted(present - set(files))
    if extra:
        raise SystemExit('Payload file not in its BOM: ' + extra[0])
    return bom


def _reject_symlinks(path, root):
    # Lexical ancestors below the guest's / too: a redirected folder must not let the copy land elsewhere.
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError('Symlink in install path refused: ' + str(current))


def _digest(p):
    return _sha(p) if p.is_file() else None


def apply(payload, *, apply=True, cold_bootstrap=False, root=Path('/'), run=subprocess.run,
          check_output=subprocess.check_output):
    payload, root = Path(payload), Path(root)
    bom = verify(payload)
    if cold_bootstrap:
        raise SystemExit('A code-only update cannot upgrade a legacy disk; it needs the full guest update')
    if not apply:
        print('Preflight passed: code-only guest update, %d files.' % len(bom['files']))
        return 0
    guard = _guard()
    targets = sorted(r[len('overlay/'):] for r in bom['files'] if r.startswith('overlay/'))
    backup = root / 'var/lib/wizard/patches' / PATCH
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup, 0o700)
    # A failed new attempt must never leave a stale success receipt.
    if (backup / 'applied.json').exists():
        (backup / 'applied.json').replace(backup / ('applied-history-%d.json' % time.time_ns()))
    previous = backup / ('code-only-previous-%d' % time.time_ns())
    data = root / HERMES_DATA
    protected = [data / 'SOUL.md', data / '.env', data / 'auth.json']

    def auth_snapshot():
        path = data / 'auth.json'
        raw = path.read_bytes() if path.is_file() else None
        return (hashlib.sha256(raw).hexdigest() if raw is not None else None,
                guard.auth_snapshot(json.loads(raw) if raw is not None else None))

    before = {str(p): _digest(p) for p in protected}
    env_path = data / '.env'
    before_env = env_path.read_bytes() if env_path.is_file() else b''
    before_auth_hash, before_auth = auth_snapshot()
    before[str(data / 'auth.json')] = before_auth_hash

    # Back up what is replaced (code only, no account data), then install.
    for rel in targets:
        src, dst = payload / 'overlay' / rel, root / rel
        _reject_symlinks(src, payload)
        _reject_symlinks(dst, root)
        if dst.is_file():
            keep = previous / rel
            keep.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(dst, keep)
            os.chmod(keep, 0o600)
    for rel in targets:
        src, dst = payload / 'overlay' / rel, root / rel
        dst.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        _reject_symlinks(dst, root)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o755 if src.stat().st_mode & 0o111 else 0o644)

    if any(rel.startswith(UNITS) for rel in targets):
        run(['systemctl', 'daemon-reload'], check=True)
        if 'etc/systemd/system/wizard-local-routes.timer' in targets:
            run(['systemctl', 'enable', 'wizard-local-routes.timer'], check=True, stdout=subprocess.DEVNULL)
    if DNS in targets:
        # The guest's resolver reads the drop-in only when it starts (try-wizard#155).
        run(['systemctl', 'restart', 'systemd-resolved'], check=True)
    if all(rel in targets for rel in WINDOW_DOOR):
        # nginx reads the generated route files; check the new config before it replaces the running one.
        run(['/opt/wizard/bin/wizard-local-routes'], check=True, stdout=subprocess.DEVNULL)
        run(['/usr/sbin/nginx', '-t', '-q', '-c', '/opt/wizard/local-proxy.conf'], check=True)
    # Only the Mac window door and the setup page restart; the agent and apps keep running.
    run(['systemctl', 'restart', 'wizard-local-proxy', 'wizard-setup'], check=True)
    if 'etc/systemd/system/wizard-local-routes.timer' in targets:
        run(['systemctl', 'start', 'wizard-local-routes.timer'], check=True)
    run(['systemctl', 'is-active', '--quiet', 'wizard-local-proxy', 'wizard-setup'], check=True)

    service_cid = check_output(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.service=wizard-shell'], text=True).strip()
    if not service_cid or '\n' in service_cid:
        raise SystemExit('Ambiguous WizardOS Service container')
    service_image = check_output(['docker', 'inspect', service_cid, '--format', '{{.Image}}'], text=True).strip()
    if not service_image.startswith('sha256:'):
        raise SystemExit('WizardOS Service image unknown')

    after = {str(p): _digest(p) for p in protected}
    after_auth_hash, after_auth = auth_snapshot()
    after[str(data / 'auth.json')] = after_auth_hash
    auth_report = guard.compare_auth(before_auth, after_auth)
    env_report = guard.compare_env(before_env, env_path.read_bytes() if env_path.is_file() else b'')
    report = {'patch': PATCH, 'kind': 'code-only', 'at': int(time.time()), 'source_pins': bom.get('sources', {}),
              'runtime_bom_sha256': _sha(payload / 'runtime-bom.json'), 'installed': targets,
              'restarted': (['systemd-resolved'] if DNS in targets else []) + ['wizard-local-proxy', 'wizard-setup'], 'service_image': service_image,
              'protected_files_byte_unchanged': before == after, 'protected_before_sha256': before,
              'protected_after_sha256': after, 'env': env_report, 'auth': auth_report,
              'permanent_identity_credentials_preserved': auth_report['stable_identity_credentials_preserved']}
    managed = root / 'opt/wizard/managed-runtime.json'
    if managed.is_file():
        # The managed runtime an earlier full update installed is untouched; keep saying which one it is.
        report['managed_runtime_image'] = json.loads(managed.read_text()).get('image')
    (backup / 'preservation-latest.json').write_text(json.dumps(report, sort_keys=True) + '\n')
    # auth.json may rotate a stock token while the agent keeps running (compare_auth allows exactly that), and .env
    # is judged byte for byte by compare_env; every other protected file must be unchanged.
    other_changed = [Path(p).name for p in before if before[p] != after[p] and Path(p).name not in ('auth.json', '.env')]
    if other_changed or not env_report['stable_credentials_preserved'] or not auth_report['stable_identity_credentials_preserved'] \
            or auth_report.get('unexpected_field_changes'):
        (backup / 'preservation-failure.json').write_text(json.dumps(report, sort_keys=True) + '\n')
        raise SystemExit('Protected state changed during a code-only update; no success receipt')
    (backup / 'applied.json').write_text(json.dumps(report, sort_keys=True) + '\n')
    print('Code-only guest update applied: %d files; restarted the Mac window door and the setup page. '
          'Agent, accounts, chats and apps were not touched.' % len(targets))
    return 0
