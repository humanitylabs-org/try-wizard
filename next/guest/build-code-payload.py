#!/usr/bin/env python3
"""Assemble the code-only guest update a Mac release carries (try-wizard#123).

Since the Mac release moved to GitHub Actions (try-wizard#102) a release had no guest update, so fixes in
next/guest/overlay never reached a Mac that updates. The full mac-stack-v1 payload (build-runtime-payload.py:
Service image, managed Hermes image, WAM) can only be built on the owned arm64 build machine. This one is code
only: this repo's guest files for the setup page (front door) and the Mac window door, a few hundred KB, no
images and no agent changes. The app's existing guest update installs it (next/mac/UPDATER.md, Bounded guest
activation): stopped-disk copy first, put back on failure.

Layout (GUEST_UPDATE_PAYLOAD for next/mac/build.sh, copied to Contents/Resources/GuestUpdate):
  source/next/guest/{upgrade-mvp-stack.py,code-update.py,stack-preservation.py}  the guest-side installer
  overlay/<absolute path in the guest>                                           the files it installs
  runtime-bom.json  {"kind": "code-only", "files": {relative path: sha256}, ...}

Runs on the macOS release runner (system python3), so it stays Python 3.9 compatible.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

GUEST = Path(__file__).resolve().parent
REPO = GUEST.parents[1]
OVERLAY = GUEST / 'overlay'
# The guest-side installer. upgrade-mvp-stack.py is the fixed entry point the Host runs
# (next/mac/Shared/GuestPatchCommand.swift); it hands a code-only payload to code-update.py.
INSTALLER = ('upgrade-mvp-stack.py', 'code-update.py', 'stack-preservation.py')
# What a code-only update installs, relative to the guest's /. Directories are taken whole (minus tests).
# Left out on purpose: the agent side (product-plugin, wizard-product-configure, wizard-runtime-configure,
# wizard-agent-ssh-migrate, agent-runtime) needs configure runs and image changes that only the full payload makes.
CODE = (
    # The setup page and front door (wizard-setup.service) and the tools it calls.
    'opt/wizard/setup',
    'opt/wizard/bin/wizard-setup-start',
    'opt/wizard/bin/wizard-env',
    'opt/wizard/bin/wizard-open-url',
    'opt/wizard/bin/wizard-import-hermes',
    'opt/wizard/bin/wizard-apps',
    'opt/wizard/bin/wizard-phone-access',
    'opt/wizard/private-access',
    # The Mac window door (wizard-local-proxy.service) with the route generator and units it needs since #98.
    'opt/wizard/local-proxy.conf',
    'opt/wizard/local-proxy-owner.inc',
    'opt/wizard/bin/wizard-local-routes',
    'opt/wizard/bin/wizard-shell-port',
    'opt/wizard/bin/wizard-ux-bridge',
    'etc/systemd/system/wizard-local-proxy.service',
    'etc/systemd/system/wizard-local-routes.service',
    'etc/systemd/system/wizard-local-routes.timer',
    # A second DNS route next to the Mac's NAT DNS, so image pulls resolve on every Mac (try-wizard#155).
    'etc/systemd/resolved.conf.d/50-wizard-dns.conf',
    # What this Mac app does for the guest: its own calls to owner routes carry the browser boundary's shell token,
    # so the App Manager may turn the boundary on in a Mac guest too (wizard-os#133, wam browser_boundary.mac_guest).
    'opt/wizard/host-capabilities.json',
)
SKIP_PARTS = {'__pycache__', 'tests', 'testing', '.DS_Store'}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def members(rel):
    src = OVERLAY / rel
    if src.is_symlink():
        raise SystemExit('Symlink in guest overlay refused: ' + rel)
    if src.is_file():
        return [rel]
    if not src.is_dir():
        raise SystemExit('Missing guest overlay file: ' + rel)
    out = []
    for p in sorted(src.rglob('*')):
        parts = set(p.relative_to(OVERLAY).parts)
        if parts & SKIP_PARTS or p.suffix == '.pyc':
            continue
        if p.is_symlink():
            raise SystemExit('Symlink in guest overlay refused: ' + str(p.relative_to(OVERLAY)))
        if p.is_file():
            out.append(str(p.relative_to(OVERLAY)))
    return out


def revision():
    try:
        return subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def build(out, source_rev=None):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    files = {}
    for name in INSTALLER:
        dst = out / 'source/next/guest' / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(GUEST / name, dst)
        files['source/next/guest/' + name] = sha(dst)
    for rel in CODE:
        for member in members(rel):
            dst = out / 'overlay' / member
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(OVERLAY / member, dst)
            files['overlay/' + member] = sha(dst)
    bom = {'schema': 1, 'kind': 'code-only', 'architecture': 'arm64',
           'sources': {'source': source_rev or revision()},
           'recipe': 'try-wizard guest files only (setup page and Mac window door); no images, no agent changes',
           'files': dict(sorted(files.items()))}
    (out / 'runtime-bom.json').write_text(json.dumps(bom, indent=2, sort_keys=True) + '\n')
    return bom


def main(argv=None):
    p = argparse.ArgumentParser(description='Assemble the code-only guest update a Mac release carries.')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--source-rev', help='commit the payload is built from (default: git HEAD)')
    a = p.parse_args(argv)
    bom = build(a.out, a.source_rev)
    size = sum((a.out / f).stat().st_size for f in bom['files'])
    print('Code-only guest update: %d files, %d bytes, source %s' % (len(bom['files']), size, bom['sources']['source']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
