#!/usr/bin/env python3
"""Extract the guest update payload (Contents/Resources/GuestUpdate) from a published Wizard update archive.

The guest payload (wizard-shell.tar, wizard-hermes-managed.tar, WAM, guest overlay and the cold-bootstrap
source) cannot be rebuilt on a clean GitHub runner: it is assembled from a locally built base image and
pinned Service/WAM sources. Until that build is reproducible, a release reuses the payload of the last
published release unchanged. The archive is pinned by SHA-256, and every extracted file is checked against
that release's own wizard-release.json, so the payload is byte-identical to what users already run.

Usage: fetch-guest-payload.py --url URL --sha256 HEX --output DIR [--archive PATH]
Prints a JSON receipt. --archive uses an already downloaded copy (still hash-checked).
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

APP = 'Wizard.app/'
PREFIX = 'Contents/Resources/GuestUpdate/'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def extract(archive, expected_sha, output):
    actual = sha256(archive)
    if actual != expected_sha:
        raise SystemExit(f'archive SHA-256 mismatch: expected {expected_sha}, got {actual}')
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read(APP + 'Contents/Resources/wizard-release.json'))
        if manifest.get('guestPatch') != 'mac-stack-v1':
            raise SystemExit('published release has no mac-stack-v1 guest payload')
        expected = {k[len(PREFIX):]: v for k, v in manifest['files'].items() if k.startswith(PREFIX)}
        if not expected:
            raise SystemExit('published release lists no guest payload files')
        output = pathlib.Path(output)
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        root = output.resolve()
        seen = set()
        for info in z.infolist():
            name = info.filename
            if not name.startswith(APP + PREFIX) or info.is_dir():
                continue
            rel = name[len(APP + PREFIX):]
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SystemExit(f'refusing symlink in payload: {rel}')
            if rel not in expected:
                raise SystemExit(f'payload file not in release manifest: {rel}')
            dest = (output / rel).resolve()
            if root not in dest.parents:
                raise SystemExit(f'unsafe payload path: {rel}')
            dest.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            with z.open(info) as src, open(dest, 'wb') as out:
                for chunk in iter(lambda: src.read(1 << 20), b''):
                    h.update(chunk)
                    out.write(chunk)
            if h.hexdigest() != expected[rel]:
                raise SystemExit(f'payload digest mismatch: {rel}')
            os.chmod(dest, stat.S_IMODE(mode) or 0o644)
            seen.add(rel)
        missing = sorted(set(expected) - seen)
        if missing:
            raise SystemExit(f'payload files missing from archive: {missing[:5]}')
    total = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    return {'source_build': manifest['build'], 'source_release_id': manifest['releaseID'],
            'archive_sha256': actual, 'files': len(seen), 'bytes': total, 'guestPatch': manifest['guestPatch']}


def main():
    p = argparse.ArgumentParser(description='Extract the published guest update payload')
    p.add_argument('--url', required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--archive', help='existing local copy of the archive (still SHA-256 checked)')
    a = p.parse_args()
    if not a.url.startswith('https://'):
        raise SystemExit('HTTPS archive URL required')
    if a.archive:
        print(json.dumps(extract(a.archive, a.sha256.lower(), a.output)))
        return
    with tempfile.TemporaryDirectory(prefix='guest-payload-') as tmp:
        archive = pathlib.Path(tmp) / 'published.zip'
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '3',
                        '--output', str(archive), a.url], check=True)
        print(json.dumps(extract(archive, a.sha256.lower(), a.output)))


if __name__ == '__main__':
    sys.exit(main())
