#!/usr/bin/env python3
"""Losslessly gzip embedded Docker saves; keep existing names/load/rollback paths.

Only a fresh output copy is written. No images are pulled/rebuilt, and no guest or
owner state is opened. Docker load detects compression by magic, not extension.
Release BOM hashes cover the *compressed* transport, with a separate independent
decoded SHA256 readback proving identical original Docker archive bytes.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil


def sha(path, decoded=False):
    h = hashlib.sha256()
    opener = gzip.open if decoded else open
    with opener(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def validate(root, bom):
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('Nonregular payload member: ' + str(path.relative_to(root)))
    for name, expected in bom.get('files', {}).items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe BOM member: ' + name)
        if sha(root / relative) != expected:
            raise ValueError('BOM digest mismatch: ' + name)
    expected = {'wizard-shell.tar': bom['payload_sha256']}
    if bom.get('managed_runtime'):
        if bom['managed_runtime']['archive'] != 'wizard-hermes-managed.tar':
            raise ValueError('Unknown managed archive')
        expected['wizard-hermes-managed.tar'] = bom['managed_runtime']['sha256']
    for name, digest in expected.items():
        if sha(root / name) != digest:
            raise ValueError('Archive digest mismatch: ' + name)
    return expected


def compress(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError('Output must be fresh and outside source')
    bom = json.loads((source / 'runtime-bom.json').read_text())
    archives = validate(source, bom)  # refuse corrupt input before creating output
    shutil.copytree(source, output, symlinks=False)
    rows = {}
    for name, original_sha in archives.items():
        path = output / name
        with path.open('rb') as f:
            already_gzip = f.read(2) == b'\x1f\x8b'
        decoded_sha = sha(path, decoded=True) if already_gzip else original_sha
        before = path.stat().st_size
        if not already_gzip:
            temporary = path.with_suffix('.tar.gzip-building')
            with path.open('rb') as src, temporary.open('xb') as raw:
                with gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=6, mtime=0) as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                raw.flush()
                os.fsync(raw.fileno())
            # Verify before replacing the copied source, even on a zero/partial write.
            if not temporary.stat().st_size or sha(temporary, decoded=True) != decoded_sha:
                raise ValueError('Compressed readback mismatch: ' + name)
            temporary.replace(path)
        if sha(path, decoded=True) != decoded_sha:
            raise ValueError('Decoded readback mismatch: ' + name)
        packed_sha, size = sha(path), path.stat().st_size
        rows[name] = dict(inputBytes=before, bytes=size, inputSha256=original_sha,
                          decodedSha256=decoded_sha, sha256=packed_sha, compression='gzip')
        if name == 'wizard-shell.tar':
            bom.update(payload_sha256=packed_sha, payload_bytes=size)
        else:
            bom['managed_runtime'].update(sha256=packed_sha, bytes=size)
        if name in bom.get('files', {}):
            bom['files'][name] = packed_sha
    (output / 'runtime-bom.json').write_text(json.dumps(bom, indent=2) + '\n')
    validate(output, bom)
    return dict(schema=1, archives=rows, decodedBytesVerified=True,
                imageIdentityUnchanged=True, guestExecuted=False, publishing=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--receipt', required=True, type=Path)
    a = p.parse_args()
    if (a.receipt.exists() or a.receipt.resolve().is_relative_to(a.source.resolve())
            or a.receipt.resolve().is_relative_to(a.output.resolve())):
        raise ValueError('Receipt must be fresh and outside input/output')
    receipt = compress(a.source, a.output)
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    a.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
