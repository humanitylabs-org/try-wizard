"""Retained build-307 cleanup, only after guest-apply's pristine gate.

Existing owners must use WAM's state-preserving shell-split command. A never-
onboarded factory has no owner state to migrate and must not retain the old
combined gateway or the Parakeet-on-Hermes recipe under new image bindings.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

LEGACY_OVERLAY_SHA256 = '560d1ce7da00efbecfafff687fc9d14e1e92594601b3eb5381da9de2c65e1fa9'
VOICE_OVERLAY_SHA256 = '34ee96f5a0b108b82ae094b0a333c968b9b0778b725dc96220eebe440a7a5d53'


def remove_known_overlay(path, expected):
    if not path.exists():
        return False
    assert not path.is_symlink() and path.is_file(), 'unsafe factory overlay'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'unknown factory overlay: ' + str(path)
    path.unlink()
    return True


def empty_legacy_state(data):
    assert not data.is_symlink(), 'legacy state symlink refused'
    for path in data.rglob('*'):
        assert not path.is_symlink(), 'legacy state symlink refused'
        if path.suffix in ('.db', '.sqlite', '.sqlite3'):
            with contextlib.closing(sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)) as conn:
                for table in ('sessions', 'messages', 'threads', 'runs'):
                    if conn.execute('select name from sqlite_master where name=?', (table,)).fetchone():
                        assert conn.execute('select count(*) from ' + table).fetchone()[0] == 0, 'legacy owner state refused'


def clean_overlays(rt, work):
    removed = []
    for app, expected in (('wizard-shell', LEGACY_OVERLAY_SHA256), ('transcriber', VOICE_OVERLAY_SHA256)):
        path = rt / 'user-config/wizardapps' / app / 'docker-compose.yml'
        if remove_known_overlay(path, expected):
            removed.append(str(path))
    (work / 'factory-overlays.json').write_text(json.dumps({'removed': removed}, indent=2) + '\n')


def retire_hidden_managed_runtime(work, inherited, active_ids,
                                  manifest=Path('/opt/wizard/managed-runtime.json')):
    """Retire only the captured factory image's stale, now-hidden selection.

    The pristine gate runs before store.enable. WAM's managed renderer outranks
    security digest overlays, so this manifest must not survive into get.sh.
    guest-apply rebuilds and re-publishes it from the selected stock image after
    strict install; never copy the obsolete image into the new Docker store.
    """
    assert not manifest.is_symlink(), 'managed runtime manifest symlink refused'
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text())
    engines = [c for c in inherited if (c['Config'].get('Labels') or {}).get(
        'com.docker.compose.service') == 'hermes-agent-engine']
    assert len(engines) == 1, 'retained managed engine missing/ambiguous'
    engine = engines[0]
    labels = engine['FactoryImage']['Config'].get('Labels') or {}
    stock = 'f97608f178d1ffeca59860195ab7da295f7c8e5f'
    assert data == {'image': engine['Image'], 'stock': stock}, 'unknown factory managed manifest'
    assert labels.get('ai.wizards.managed-launch') == '1', 'unmanaged retained engine'
    assert labels.get('ai.wizards.stock-revision') == stock, 'unknown retained stock contract'
    assert data['image'] not in active_ids, 'retained managed image still active'
    archived = work / 'retired-managed-runtime.json'
    assert not archived.exists() and not archived.is_symlink(), 'retirement evidence already exists'
    archived.write_bytes(manifest.read_bytes())
    archived.chmod(0o600)
    manifest.unlink()
    return data


def factory_manager(root, rt):
    import sys
    sys.path.insert(0, str(root / 'final/wam'))
    from wam.cli import Config, installed_ids
    os.environ['WIZARD_OS_HOME'] = '/home/wizard/.wizard-os'
    c = Config()
    c.runtipi_root = rt
    return c.runtipi()


def prepare(root, rt, work, invoke):
    """Retire only the gated pristine legacy install, through its lifecycle API."""
    manager = factory_manager(root, rt)
    empty_legacy_state(rt / 'app-data/wizardapps/wizard-shell/data')
    # Authenticated lifecycle API; no database surgery and no second gateway writer.
    from wam.cli import installed_ids
    retire_legacy(manager, lambda: installed_ids(manager))
    receipt = {'legacyUninstalled': True, 'ownerMigration': 'wam shell-split (not a factory reset)'}
    (work / 'factory-migrations.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def default_states(manager, release):
    states = {}
    for row in release['default_apps'].values():
        if row and row.get('app'):
            app = row['app']
            state = manager.wait_status(app + ':wizardapps', {'running'}, timeout=300)
            states[app] = state
            assert state == 'running', 'factory default not running: ' + app + ': ' + str(state)
    return states


def retire_legacy(manager, installed):
    legacy = 'wizard-shell'
    if legacy in installed():
        manager.stop(legacy + ':wizardapps')
        assert manager.wait_status(legacy + ':wizardapps', {'stopped'}, timeout=300) == 'stopped'
        manager.uninstall(legacy + ':wizardapps')
        assert manager.wait_status(legacy + ':wizardapps', {'missing'}, timeout=300) == 'missing'
    assert legacy not in installed(), 'legacy combined shell still installed'


def trust_local_host(data, public_key):
    """Trust the local guest's key, not a network scan/TOFU or disabled checking."""
    fields = public_key.read_text().split()
    assert len(fields) >= 2 and fields[0] == 'ssh-ed25519', 'missing guest ED25519 public key'
    directory = data / '.ssh'
    assert not directory.is_symlink()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'known_hosts'
    assert not path.is_symlink()
    # This route is factory-managed and its host key is regenerated on recipient boot.
    old = path.read_text().splitlines() if path.exists() else []
    keep = [line for line in old if line.split(' ', 1)[0] not in ('wizard-vm', '[wizard-vm]:22')]
    path.write_text('\n'.join(keep + ['wizard-vm ' + ' '.join(fields[:2])]) + '\n')
    os.chown(directory, 1000, 1000)
    os.chown(path, 1000, 1000)
    directory.chmod(0o700)
    path.chmod(0o600)
    return path


if __name__ == '__main__':
    assert os.geteuid() == 0
    trust_local_host(Path('/home/wizard/runtipi/app-data/wizardapps/hermes-agent/data'),
                     Path('/etc/ssh/ssh_host_ed25519_key.pub'))
