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
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import tarfile
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


def extract(archive, destination):
    destination.mkdir()
    seen = set()
    with tarfile.open(archive, mode='r|xz') as tar:
        for member in tar:
            name = member.name.removeprefix('./')
            if member.isdir() and name.rstrip('/') in ('', '.', 'boot'):
                continue
            require(member.isfile() and name in ('manifest.json', 'bom.json', 'boot/vmlinux', 'boot/initrd', 'rootfs.img'),
                    'Unexpected archive member: ' + name)
            require(name not in seen, 'Duplicate archive member')
            seen.add(name)
            ceiling = MAX_ROOTFS if name == 'rootfs.img' else (GIB if name.startswith('boot/') else 1024 ** 2)
            require(0 < member.size <= ceiling, 'Invalid member size')
            target = destination / name
            target.parent.mkdir(exist_ok=True, parents=True)
            source = tar.extractfile(member)
            require(source is not None, 'Missing member stream')
            count = 0
            with target.open('xb') as out:
                for chunk in iter(lambda: source.read(8 * 1024 ** 2), b''):
                    count += len(chunk)
                    if chunk.count(0) == len(chunk):
                        out.seek(len(chunk), 1)
                    else:
                        out.write(chunk)
                out.truncate(count)
            require(count == member.size, 'Short archive member')
    require(seen - {'bom.json'} == {'manifest.json', 'boot/vmlinux', 'boot/initrd', 'rootfs.img'}, 'Incomplete archive')


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
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--feed-file', type=Path, required=True)
    p.add_argument('--feed-sha256', required=True)
    p.add_argument('--feed-url', required=True)
    p.add_argument('--source-sha', required=True)
    p.add_argument('--work', type=Path, required=True)
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
        archive = work / 'original.tar.xz'
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
        require(archive.stat().st_size == feed['bytes'] and sha(archive) == feed['sha256'], 'Invalid full archive')
        baseline = work / 'baseline'
        extract(archive, baseline)
        manifest = verify_manifest(baseline)
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
                                    'manifest.json', 'boot', 'rootfs.img', *extras], stdout=subprocess.PIPE)
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
        # Independent streamed archive readback hashes, without another 50GB allocation.
        seen = {}
        with tarfile.open(target, mode='r|xz') as tar:
            for member in tar:
                if member.isdir() and member.name.rstrip('/') == 'boot':
                    continue
                require(member.isfile() and member.name in ['manifest.json', *manifest['files'], *extras], 'Bad output member')
                require(member.name not in seen, 'Duplicate output member')
                stream = tar.extractfile(member)
                seen[member.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(set(seen) == {'manifest.json', *manifest['files'], *extras}, 'Incomplete output')
        require(all(seen[name] == digest for name, digest in manifest['files'].items()), 'Output readback mismatch')
        require(all(seen[name] == sha(candidate / name) for name in extras), 'Original BOM readback mismatch')
        require(seen['manifest.json'] == sha(candidate / 'manifest.json'), 'Output manifest changed')
        receipt.update(phase='candidate-only-complete', candidateArchiveBytes=target.stat().st_size,
                       candidateArchiveSha256=sha(target), candidateLogicalBytes=disk.stat().st_size,
                       candidateAllocatedBytes=disk.stat().st_blocks * 512, conservativeInstallBytes=manifest['installBytes'],
                       filesystemInventory=before, filesystemClosureUnchanged=True, originalUnchanged=True,
                       archiveReadbackVerified=True, freeAfterBytes=shutil.disk_usage(work).free)
        save()
    except Exception as exc:
        receipt.update(phase='failed', error=repr(exc))
        save()
        raise
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
