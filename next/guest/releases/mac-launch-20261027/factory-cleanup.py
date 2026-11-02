#!/usr/bin/env python3
"""Trim only a pristine disposable factory. App removal is owned by WAM."""
import json
import sys
import subprocess
from pathlib import Path


def trim(allowed, deferred=(), final=False):
    sys.path.insert(0, '/home/wizard/wizard-app-manager')
    from wam import cli
    c = cli.Config()
    have = set(cli.installed_ids(c.runtipi()))
    remove = (have - set(allowed)) if final else (have & set(deferred))
    for app in sorted(remove):
        cli.uninstall(c, app, force=True)
    assert not (set(cli.installed_ids(c.runtipi())) & remove), 'WAM removal failed'
    # WAM preserves data on uninstall. Safe to discard only in the never-onboarded
    # factory clone; guest-apply.pristine() is required immediately before this call.
    stale = set()
    if final:
        for parent in ('app-data', 'user-config'):
            stale.update(p.name for p in (c.runtipi_root / parent / cli.STORE).glob('*')
                         if p.name not in set(allowed))
    for app in remove | set(deferred) | stale:
        for parent in ('app-data', 'user-config'):
            p = c.runtipi_root / parent / cli.STORE / app
            if p.exists():
                subprocess.run(['sudo', '-n', 'rm', '-rf', '--', str(p)], check=True)
    cli.write_registry(c, c.runtipi())
    return sorted(remove)


def prune(keep):
    def docker(*args):
        return subprocess.check_output(['docker', *args], text=True)
    # Stopped factory containers otherwise keep the obsolete images reachable.
    docker('container', 'prune', '-f')
    used = set()
    ids = docker('ps', '-aq').split()
    if ids:
        used.update(c['Image'] for c in json.loads(docker('inspect', *ids)))
    for ref in keep:
        used.add(json.loads(docker('image', 'inspect', ref))[0]['Id'])
    for image in set(docker('image', 'ls', '-aq', '--no-trunc').split()) - used:
        docker('image', 'rm', '-f', image)
    docker('builder', 'prune', '-af')
    cache = Path('/var/lib/apt/lists')
    for p in cache.glob('*'):
        if p.is_file():
            p.unlink()
    subprocess.run(['apt-get', 'clean'], check=True)


if __name__ == '__main__':
    args = json.loads(sys.argv[1])
    print(json.dumps(trim(args['allowed'], args['deferred'], args['final'])))
