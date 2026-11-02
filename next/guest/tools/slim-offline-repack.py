#!/usr/bin/env python3
"""Candidate-only, no-deletion offline factory repack for the admitted Linux worker.

Uses the existing minimal-factory compactor, not a second factory implementation.
Never starts Docker/containerd/VMs, removes stores or changes feeds. Mounted file
inventories must match exactly before/after. This is not ARM/onboarding acceptance.
"""
import argparse
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import urllib.parse

GIB = 1024 ** 3
# Bound from the observed public 0.5.0 rootfs plus two fully allocated copies,
# source/candidate archives and conservative overhead. Free already excludes old jobs.
MAX_ROOTFS = 52 * GIB
RESERVE = 80 * GIB
REQUIRED = 2 * MAX_ROOTFS + 30 * GIB + RESERVE
HERE = Path(__file__).resolve().parent


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(argv, timeout=900, **kw):
    return subprocess.run(list(map(str, argv)), check=True, timeout=timeout, **kw)


FILES = {'manifest.json', 'boot/vmlinux', 'boot/initrd', 'rootfs.img'}


def gnu_tar_args(archive):
    # Do not inherit TAR_OPTIONS (or a locale-dependent verbose-list grammar).
    return ['tar', '--force-local', '--quoting-style=escape', '-f', str(archive)]


def tar_env():
    return {**os.environ, 'TAR_OPTIONS': '', 'LC_ALL': 'C', 'TZ': 'UTC'}


def checked_xz(archive):
    """Consume through the XZ checksum/footer; tar may stop before that footer.

    Bound the expanded physical archive, and require complete tar end markers.
    No decompressed spool or additional disk-sized allocation is needed.
    """
    count, tail = 0, b''
    with lzma.open(archive) as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 ** 2), b''):
            count += len(chunk)
            require(count <= MAX_ROOTFS + 3 * GIB, 'Expanded archive exceeds bound')
            tail = (tail + chunk)[-1024:]
    require(count % 512 == 0 and tail == bytes(1024), 'Missing tar end markers')
    return count


def archive_members(archive, extras=('bom.json',)):
    """Use GNU tar's sparse-aware logical sizes, never Python's PAX size order.

    In the public archive GNU.sparse.realsize precedes POSIX size. Python 3.13
    applies the latter last, truncating logical size and corrupting next offset.
    GNU tar interprets both correctly. No archive-controlled path is written
    until the entire bounded, typed, unique allowlisted catalogue is accepted.
    --ignore-zeros also validates/rejects members hidden after an end marker.
    """
    checked_xz(archive)
    rows, seen = {}, set()
    argv = [*gnu_tar_args(archive), '--list', '--verbose', '--numeric-owner',
            '--full-time', '--utc', '--ignore-zeros', '--warning=all']
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=tar_env()) as proc:
        try:
            for _ in range(17):
                line = proc.stdout.readline(4097)
                if not line:
                    break
                require(len(line) <= 4096 and line.endswith(b'\n'), 'Oversized tar listing')
                fields = line.decode('ascii', errors='strict').rstrip('\n').split(maxsplit=5)
                require(len(fields) == 6, 'Unknown GNU tar listing grammar')
                mode, owner, size, date, clock, raw = fields
                require(len(mode) == 10 and mode[0] in '-d', 'Nonregular archive member')
                if mode[0] == 'd':
                    require(raw in ('.', './', 'boot', 'boot/', './boot', './boot/'),
                            'Unexpected archive directory spelling')
                name = raw.removeprefix('./').rstrip('/') if mode[0] == 'd' else raw.removeprefix('./')
                if mode[0] == 'd' and name == '':
                    name = '.'
                require(name not in seen, 'Duplicate archive member')
                seen.add(name)
                if mode[0] == 'd':
                    require(name in ('', '.', 'boot') and int(size) == 0, 'Unexpected archive directory')
                    continue
                require(name in FILES | set(extras), 'Unexpected archive member: ' + name)
                ceiling = MAX_ROOTFS if name == 'rootfs.img' else (GIB if name.startswith('boot/') else 1024 ** 2)
                require(0 < int(size) <= ceiling, 'Invalid member size')
                rows[name] = dict(raw=raw, bytes=int(size))
            else:
                raise ValueError('Too many archive members')
            # Small fixed archive vocabulary makes bounded stderr sufficient.
            error = proc.stderr.read(4097)
            require(proc.wait(timeout=120) == 0 and not error, 'GNU tar catalogue failed')
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=30)
    require(set(rows) - set(extras) == FILES, 'Incomplete archive')
    return rows


def extract(archive, destination):
    rows = archive_members(archive)
    destination.mkdir(mode=0o700)
    # GNU tar rejects --no-overwrite-dir together with --keep-old-files.
    # Keep fail-on-existing-file semantics in the fresh exclusive destination.
    run([*gnu_tar_args(archive), '--extract', '--sparse', '--no-same-owner',
         '--no-same-permissions', '--keep-old-files',
         '--no-recursion', '-C', destination, '--', *[r['raw'] for r in rows.values()]],
        timeout=3600, env=tar_env())
    for name, row in rows.items():
        path = destination / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == row['bytes'],
                'Extracted size/type mismatch: ' + name)
    return rows


def archive_readback(archive, root, extras=(), rows=None):
    """Independent stdout expansion, byte counts and hashes; no extraction reuse.

    GNU tar -O expands sparse holes. This verifies the actual archive bytes
    against the files/manifest, rather than hashing the extraction again.
    """
    rows = archive_members(archive, extras) if rows is None else rows
    seen = {}
    for name, row in rows.items():
        count, digest = 0, hashlib.sha256()
        with subprocess.Popen([*gnu_tar_args(archive), '--extract', '--to-stdout',
                               '--no-recursion', '--', row['raw']],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=tar_env()) as proc:
            try:
                for chunk in iter(lambda: proc.stdout.read(8 * 1024 ** 2), b''):
                    count += len(chunk)
                    require(count <= row['bytes'], 'Oversized readback: ' + name)
                    digest.update(chunk)
                error = proc.stderr.read(4097)
                require(proc.wait(timeout=120) == 0 and not error, 'GNU tar readback failed')
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=30)
        require(count == row['bytes'] == (root / name).stat().st_size, 'Short readback: ' + name)
        require(digest.hexdigest() == sha(root / name), 'Archive readback mismatch: ' + name)
        seen[name] = dict(bytes=count, sha256=digest.hexdigest())
        print(json.dumps(dict(archiveReadbackMember=name, **seen[name])), flush=True)
    return seen


def verify_feed_archive(archive, feed):
    """Revalidate unchanged cached bytes, including every frozen feed part."""
    require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size == feed['bytes'],
            'Invalid cached archive size/type')
    whole = hashlib.sha256()
    with archive.open('rb') as src:
        for part in feed['parts']:
            left, digest = part['bytes'], hashlib.sha256()
            require(type(left) is int and left > 0, 'Invalid feed part size')
            while left:
                chunk = src.read(min(left, 8 * 1024 ** 2))
                require(chunk, 'Short cached archive')
                left -= len(chunk)
                digest.update(chunk)
                whole.update(chunk)
            require(digest.hexdigest() == part['sha256'], 'Cached part hash mismatch')
        require(not src.read(1), 'Unexpected cached archive tail')
    require(whole.hexdigest() == feed['sha256'], 'Cached full archive hash mismatch')


def census(root, output):
    """Hash file bytes + permissions/ownership/xattrs; never print private content."""
    h = hashlib.sha256()
    count = 0
    with output.open('x') as log:
        for parent, dirs, files in os.walk(root, followlinks=False):
            for name in sorted(dirs + files):
                path = Path(parent) / name
                s = path.lstat()
                row = dict(path=str(path.relative_to(root)), mode=s.st_mode, uid=s.st_uid,
                           gid=s.st_gid, rdev=s.st_rdev,
                           xattrs={key: os.getxattr(path, key, follow_symlinks=False).hex()
                                   for key in sorted(os.listxattr(path, follow_symlinks=False))})
                if stat.S_ISREG(s.st_mode):
                    row.update(bytes=s.st_size, sha256=sha(path))
                elif stat.S_ISLNK(s.st_mode):
                    row['target'] = os.readlink(path)
                encoded = json.dumps(row, sort_keys=True) + '\n'
                log.write(encoded)
                h.update(encoded.encode())
                count += 1
            dirs.sort()
    return dict(entries=count, sha256=h.hexdigest())


def mounted_inventory(image, work, label):
    mount = work / ('mount-' + label)
    mount.mkdir()
    run(['mount', '-o', 'ro,noload,loop', image, mount])
    try:
        inventory = census(mount, work / (label + '-files.jsonl'))
        if label == 'before':
            # Authoritative source config and last-recorded mappings, NOT live daemon proof.
            configs = {}
            for rel in ('etc/docker/daemon.json', 'etc/containerd/config.toml',
                        'lib/systemd/system/docker.service', 'usr/lib/systemd/system/docker.service'):
                p = mount / rel
                if p.is_file() and p.resolve().is_relative_to(mount.resolve()):
                    configs[rel] = p.read_text()
            containers = []
            for p in sorted((mount / 'var/lib/docker/containers').glob('*/config.v2.json')):
                require(p.resolve().is_relative_to(mount.resolve()) and not p.is_symlink(), 'Unsafe container config')
                d = json.loads(p.read_text())
                containers.append(dict(id=p.parent.name, name=d.get('Name'), imageID=d.get('Image'),
                                       imageRef=d.get('Config', {}).get('Image'),
                                       lastRecordedState=d.get('State', {}).get('Running')))
            compose = {}
            runtipi = mount / 'home/wizard/runtipi'
            for p in sorted(runtipi.rglob('*compose*.y*ml')):
                if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(mount.resolve()):
                    lines = [line.strip() for line in p.read_text(errors='replace').splitlines()
                             if line.strip().startswith('image:')]
                    if lines:
                        compose[str(p.relative_to(mount))] = lines
            stores = {}
            for rel in ('var/lib/docker', 'var/lib/docker/overlay2', 'var/lib/containerd'):
                p = mount / rel
                if p.exists():
                    stores[rel] = int(subprocess.check_output(['du', '-sx', '--block-size=1', p], text=True).split()[0])
            (work / 'consumer-census.json').write_text(json.dumps(dict(
                configs=configs, containers=containers, composeImageDeclarations=compose, stores=stores,
                liveDaemonInspected=False, containerdRefsParsed=False, deletionAuthorized=False), indent=2) + '\n')
        return inventory
    finally:
        run(['umount', mount], timeout=120)  # failure is fatal, never hide an owned mount


def verify_manifest(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    require(manifest.get('rootfs') == 'rootfs.img' and manifest.get('kernel') == 'boot/vmlinux'
            and manifest.get('initrd') == 'boot/initrd', 'Unknown manifest layout')
    require(set(manifest['files']) == {'rootfs.img', 'boot/vmlinux', 'boot/initrd'}, 'Unknown file closure')
    for name, digest in manifest['files'].items():
        require(sha(root / name) == digest, 'Manifest hash mismatch: ' + name)
        if 'sizes' in manifest:
            require(type(manifest['sizes'].get(name)) is int
                    and (root / name).stat().st_size == manifest['sizes'][name],
                    'Manifest size mismatch: ' + name)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--feed-file', type=Path, required=True)
    p.add_argument('--feed-sha256', required=True)
    p.add_argument('--feed-url', required=True)
    p.add_argument('--source-sha', required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--reuse-archive', type=Path, help='Read-only, fully revalidated cached source')
    a = p.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError('Worker terminated: ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    work = a.work.resolve()
    require(os.geteuid() == 0 and os.environ.get('WIZARD_HEAVY_LOCK_FD'), 'Admitted root worker required')
    require(work.is_relative_to(Path('/srv/work')) and not work.exists(), 'Fresh worker-only workdir required')
    require(sha(a.feed_file) == a.feed_sha256, 'Frozen feed changed')
    free = shutil.disk_usage(work.parent).free
    require(free >= REQUIRED, 'Insufficient free bytes: ' + str(free) + ' required=' + str(REQUIRED))
    feed = json.loads(a.feed_file.read_text())
    require(sum(part['bytes'] for part in feed['parts']) == feed['bytes'], 'Feed part total mismatch')
    work.mkdir(mode=0o700)
    receipt = dict(sourceCommit=a.source_sha, freeBeforeBytes=free, requiredFreeBytes=REQUIRED,
                   reserveBytes=RESERVE, phase='download', publishing=False, bootAccepted=False)
    def save():
        (work / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    save()
    try:
        archive = a.reuse_archive if a.reuse_archive else work / 'original.tar.xz'
        if a.reuse_archive:
            require(archive.is_absolute() and archive.resolve().is_relative_to(Path('/srv/work')),
                    'Cached archive must be worker-local')
        else:
            with archive.open('xb') as out:
                for index, part in enumerate(feed['parts']):
                    url = urllib.parse.urljoin(a.feed_url, part['url'])
                    parsed = urllib.parse.urlsplit(url)
                    require(parsed.scheme == 'https' and parsed.netloc == 'downloads.aiwizards.com', 'Unapproved part origin')
                    temporary = work / ('part-' + str(index))
                    run(['curl', '-fLsS', '-A', 'Mozilla/5.0', '--retry', '3', '--max-time', '600', url, '-o', temporary], timeout=650)
                    require(temporary.stat().st_size == part['bytes'] and sha(temporary) == part['sha256'], 'Invalid part')
                    with temporary.open('rb') as src:
                        shutil.copyfileobj(src, out, 8 * 1024 ** 2)
                    temporary.unlink()
        verify_feed_archive(archive, feed)
        receipt.update(phase='source-archive-validation', sourceArchiveSha256=feed['sha256'],
                       sourceArchiveBytes=feed['bytes'], reusedArchive=bool(a.reuse_archive))
        save()
        baseline = work / 'baseline'
        members = extract(archive, baseline)
        manifest = verify_manifest(baseline)
        baseline_readback = archive_readback(archive, baseline, ('bom.json',), members)
        receipt.update(baselineArchiveMembers=members, baselineReadback=baseline_readback)
        save()
        original = baseline / 'rootfs.img'
        original_sha = sha(original)
        receipt.update(phase='inventory', originalArchiveBytes=archive.stat().st_size,
                       originalLogicalBytes=original.stat().st_size, originalAllocatedBytes=original.stat().st_blocks * 512)
        save()
        run(['e2fsck', '-fn', original])
        before = mounted_inventory(original, work, 'before')
        candidate = work / 'candidate'
        candidate.mkdir()
        shutil.copytree(baseline / 'boot', candidate / 'boot')
        disk = candidate / 'rootfs.img'
        run(['cp', '--sparse=always', '--reflink=auto', original, disk])
        spec = importlib.util.spec_from_file_location('factory_compactor', HERE.parent / 'releases/mac-launch-20261027/compact-ext4.py')
        compactor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compactor)
        receipt.update(phase='compaction')
        save()
        receipt['compaction'] = compactor.compact(disk, '', 512 * 1024 ** 2)
        after = mounted_inventory(disk, work, 'after')
        require(before == after, 'Filesystem content/metadata changed')
        require(sha(original) == original_sha, 'Original image changed')
        old_stack = manifest['stack']
        for name in manifest['files']:
            manifest['files'][name] = sha(candidate / name)
            manifest['sizes'][name] = (candidate / name).stat().st_size
        # Conservative logical extraction floor, not an optimistic used-block estimate.
        manifest['installBytes'] = sum(manifest['sizes'].values())
        manifest['packagingCandidate'] = dict(sourceCommit=a.source_sha, originalArchiveSha256=feed['sha256'], publishing=False)
        require(manifest['stack'] == old_stack, 'Compatibility ID changed')
        (candidate / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        extras = []
        if (baseline / 'bom.json').exists():
            shutil.copy2(baseline / 'bom.json', candidate / 'original-bom.json')
            extras.append('original-bom.json')
        target = work / 'candidate.tar.xz'
        with target.open('xb') as out:
            tar = subprocess.Popen(['tar', '-C', str(candidate), '--sparse', '--hole-detection=raw', '-cf', '-',
                                    'manifest.json', 'boot', 'rootfs.img', *extras],
                                   stdout=subprocess.PIPE, env=tar_env())
            try:
                run(['xz', '-T2', '-6', '-c'], stdin=tar.stdout, stdout=out, timeout=5400)
                require(tar.wait(timeout=120) == 0, 'tar failed')
            finally:
                if tar.stdout:
                    tar.stdout.close()
                if tar.poll() is None:
                    tar.terminate()
                    tar.wait(timeout=120)
        require(target.stat().st_size > 0, 'Empty candidate archive')
        readback = archive_readback(target, candidate, extras)
        verify_feed_archive(archive, feed)
        require(sha(a.feed_file) == a.feed_sha256, 'Frozen feed changed after validation')
        receipt.update(phase='candidate-only-complete', candidateArchiveBytes=target.stat().st_size,
                       candidateArchiveSha256=sha(target), candidateLogicalBytes=disk.stat().st_size,
                       candidateAllocatedBytes=disk.stat().st_blocks * 512, conservativeInstallBytes=manifest['installBytes'],
                       filesystemInventory=before, filesystemClosureUnchanged=True, originalUnchanged=True,
                       archiveReadbackVerified=True, archiveReadback=readback,
                       freeAfterBytes=shutil.disk_usage(work).free)
        save()
    except Exception as exc:
        receipt.update(phase='failed', error=repr(exc))
        save()
        raise
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
