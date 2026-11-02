"""Small offline packer source regressions; no mount/root/image build."""
import hashlib
import importlib.util
import io
import json
import lzma
import subprocess
from unittest import mock
from pathlib import Path
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('offline_slim', HERE / 'tools/slim-offline-repack.py')
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OfflineSlimTests(unittest.TestCase):
    def archive(self, path, members):
        with tarfile.open(path, 'w:xz') as tar:
            for name, value in members:
                entry = tarfile.TarInfo(name)
                if value is None:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = '/outside'
                    tar.addfile(entry)
                else:
                    entry.size = len(value)
                    tar.addfile(entry, io.BytesIO(value))

    def test_exact_safe_extraction_and_zero_holes_readback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            data = {'manifest.json': b'{}', 'boot/vmlinux': b'kernel', 'boot/initrd': b'initrd',
                    'rootfs.img': bytes(8192) + b'nonzero', 'bom.json': b'{}'}
            self.archive(root / 'source.xz', list(data.items()))
            module.extract(root / 'source.xz', root / 'out')
            self.assertEqual({name: (root / 'out' / name).read_bytes() for name in data}, data)

    def test_archive_escape_duplicate_link_and_incomplete_fail(self):
        for rows in ([('../outside', b'x')], [('rootfs.img', None)],
                     [('rootfs.img', b'x'), ('rootfs.img', b'y')], [('rootfs.img', b'x')]):
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                self.archive(root / 'source.xz', rows)
                with self.assertRaises(ValueError):
                    module.extract(root / 'source.xz', root / 'out')
                self.assertFalse((root / 'outside').exists())

    def sparse_archive(self, path, boot_first=False):
        # Exact public PAX ordering: logical realsize, then physical POSIX size.
        # Boot after the sparse member reproduced the missing-boot failure.
        logical = 16 * 1024 ** 2
        blocks = b'A' * 4096 + b'Z' * 4096
        sparse_map = f'3\n0\n4096\n{logical - 4096}\n4096\n{logical}\n0\n'.encode()
        body = sparse_map.ljust(512, b'\0') + blocks
        data = {'rootfs.img': b'A' * 4096 + bytes(logical - 8192) + b'Z' * 4096,
                'boot/vmlinux': b'kernel', 'boot/initrd': b'initrd'}
        manifest = dict(rootfs='rootfs.img', kernel='boot/vmlinux', initrd='boot/initrd',
                        files={n: hashlib.sha256(b).hexdigest() for n, b in data.items()},
                        sizes={n: len(b) for n, b in data.items()})
        data['manifest.json'] = json.dumps(manifest).encode()
        names = ['manifest.json', 'boot/vmlinux', 'boot/initrd', 'rootfs.img'] if boot_first else [
            'manifest.json', 'rootfs.img', 'boot/vmlinux', 'boot/initrd']
        with tarfile.open(path, 'w:xz', format=tarfile.PAX_FORMAT) as tar:
            for name in names:
                entry = tarfile.TarInfo(name)
                value = data[name]
                if name == 'rootfs.img':
                    entry.name = 'GNUSparseFile.0/rootfs.img'
                    entry.pax_headers = {'GNU.sparse.major': '1', 'GNU.sparse.minor': '0',
                                         'GNU.sparse.name': name, 'GNU.sparse.realsize': str(logical),
                                         'size': str(len(body))}
                    value = body
                entry.size = len(value)
                tar.addfile(entry, io.BytesIO(value))
        return data

    def test_public_pax_size_order_sparse_and_reordered_boot(self):
        for boot_first in (False, True):
            with self.subTest(boot_first=boot_first), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                archive = root / 'sparse.xz'
                expected = self.sparse_archive(archive, boot_first)
                # Negative control pinpoints the old parser's wrong logical size.
                with tarfile.open(archive, 'r|xz') as tar:
                    sparse = next(m for m in tar if m.name == 'rootfs.img')
                    self.assertEqual(sparse.size, 8704)
                    self.assertNotEqual(sparse.size, len(expected['rootfs.img']))
                rows = module.extract(archive, root / 'out')
                self.assertEqual(set(rows), set(expected))
                for name, value in expected.items():
                    self.assertEqual((root / 'out' / name).read_bytes(), value)
                module.verify_manifest(root / 'out')
                readback = module.archive_readback(archive, root / 'out')
                self.assertEqual(readback['rootfs.img']['bytes'], len(expected['rootfs.img']))
                self.assertLess((root / 'out/rootfs.img').stat().st_blocks * 512, 1024 ** 2)

    def test_gnu_generated_old_and_pax_sparse_readback(self):
        for fmt in ('gnu', 'pax'):
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                source = root / 'source'
                (source / 'boot').mkdir(parents=True)
                for name in ('manifest.json', 'boot/vmlinux', 'boot/initrd'):
                    (source / name).write_bytes(b'bytes')
                with (source / 'rootfs.img').open('wb') as f:
                    f.write(b'start')
                    f.seek(8 * 1024 ** 2)
                    f.write(b'end')
                archive = root / 'gnu.xz'
                subprocess.run(['tar', '-C', str(source), '--format=' + fmt, '--sparse',
                                '-cJf', str(archive), 'manifest.json', 'rootfs.img', 'boot'], check=True)
                module.extract(archive, root / 'out')
                module.archive_readback(archive, root / 'out')
                self.assertEqual(module.sha(source / 'rootfs.img'), module.sha(root / 'out/rootfs.img'))

    def test_corrupt_truncated_end_marker_and_hidden_members_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / 'source.xz'
            self.sparse_archive(archive)
            good = archive.read_bytes()
            unpacked = lzma.decompress(good)
            bad_cases = [good[:-12], good[:len(good) // 2],
                         good[:-20] + bytes([good[-20] ^ 1]) + good[-19:],
                         lzma.compress(unpacked[:-1024].rstrip(b'\0'))]
            other = root / 'other.xz'
            self.archive(other, [('unknown', b'bad')])
            bad_cases.append(lzma.compress(unpacked + lzma.decompress(other.read_bytes())))
            # Valid XZ, complete member data ending in zero blocks, no tar EOF.
            # Trailer-byte checks alone must not mistake file data for EOF.
            plain = io.BytesIO()
            with tarfile.open(fileobj=plain, mode='w') as tar:
                for name, value in [('manifest.json', b'{}'), ('boot/vmlinux', b'kernel'),
                                    ('boot/initrd', b'initrd'), ('rootfs.img', bytes(8192))]:
                    entry = tarfile.TarInfo(name)
                    entry.size = len(value)
                    tar.addfile(entry, io.BytesIO(value))
                end_of_data = tar.offset
            bad_cases.append(lzma.compress(plain.getvalue()[:end_of_data]))
            for index, value in enumerate(bad_cases):
                with self.subTest(index=index):
                    archive.write_bytes(value)
                    with self.assertRaises((ValueError, EOFError, lzma.LZMAError)):
                        module.extract(archive, root / ('out' + str(index)))
                    self.assertFalse((root / ('out' + str(index))).exists())

    def test_unknown_duplicate_normalized_link_and_size_bounds_fail_before_write(self):
        for rows in ([('unknown', b'x')], [('/rootfs.img', b'x')], [('boot/../rootfs.img', b'x')],
                     [('boot/vmlinux', None)], [('rootfs.img', b'x'), ('./rootfs.img', b'y')],
                     [('rootfs.img', b'')], [('manifest.json', b'x' * (1024 ** 2 + 1))]):
            with self.subTest(names=[n for n, _ in rows]), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                self.archive(root / 'source.xz', rows)
                with self.assertRaises(ValueError):
                    module.extract(root / 'source.xz', root / 'out')
                self.assertFalse((root / 'out').exists())
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.sparse_archive(root / 'source.xz')
            with mock.patch.object(module, 'MAX_ROOTFS', 1024):
                with self.assertRaisesRegex(ValueError, 'Invalid member size'):
                    module.extract(root / 'source.xz', root / 'out')

    def test_cached_feed_revalidates_parts_whole_size_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'cached'
            p.write_bytes(b'firstsecond')
            feed = dict(bytes=11, sha256=module.sha(p), parts=[
                dict(bytes=len(v), sha256=hashlib.sha256(v).hexdigest()) for v in (b'first', b'second')])
            module.verify_feed_archive(p, feed)
            for bad in ({**feed, 'bytes': 12}, {**feed, 'sha256': '0' * 64},
                        {**feed, 'parts': [dict(bytes=11, sha256='0' * 64)]}):
                with self.assertRaises(ValueError):
                    module.verify_feed_archive(p, bad)
            (root / 'link').symlink_to(p)
            with self.assertRaises(ValueError):
                module.verify_feed_archive(root / 'link', feed)

    def test_independent_readback_and_manifest_size_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.sparse_archive(root / 'source.xz')
            module.extract(root / 'source.xz', root / 'out')
            path = root / 'out/manifest.json'
            manifest = json.loads(path.read_text())
            manifest['sizes']['rootfs.img'] -= 1
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'Manifest size mismatch'):
                module.verify_manifest(root / 'out')
            with self.assertRaisesRegex(ValueError, 'Archive readback mismatch|Short readback'):
                module.archive_readback(root / 'source.xz', root / 'out')

    def test_inventory_changes_on_bytes_permissions_and_symlink_target(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'source'
            source.mkdir()
            file = source / 'file'
            file.write_bytes(b'one')
            link = source / 'link'
            link.symlink_to('file')
            first = module.census(source, root / 'first.jsonl')
            self.assertEqual(first, module.census(source, root / 'second.jsonl'))
            file.write_bytes(b'two')
            second = module.census(source, root / 'third.jsonl')
            self.assertNotEqual(first, second)
            file.chmod(0o700)
            third = module.census(source, root / 'fourth.jsonl')
            self.assertNotEqual(second, third)
            link.unlink()
            link.symlink_to('missing')
            self.assertNotEqual(third, module.census(source, root / 'fifth.jsonl'))

    def test_manifest_hash_closure_and_unknown_layout_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'boot').mkdir()
            files = {name: hashlib.sha256(b'bytes').hexdigest()
                     for name in ('rootfs.img', 'boot/vmlinux', 'boot/initrd')}
            for name in files:
                (root / name).write_bytes(b'bytes')
            manifest = dict(rootfs='rootfs.img', kernel='boot/vmlinux', initrd='boot/initrd', files=files)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(module.verify_manifest(root), manifest)
            (root / 'rootfs.img').write_bytes(b'bad')
            with self.assertRaises(ValueError):
                module.verify_manifest(root)

    def test_existing_compactor_and_conservative_floor_are_shared(self):
        source = (HERE / 'tools/slim-offline-repack.py').read_text()
        self.assertIn('releases/mac-launch-20261027/compact-ext4.py', source)
        self.assertNotIn("['docker'", source)
        self.assertNotIn('system prune', source)
        generic = (HERE / 'build-image.sh').read_text()
        self.assertIn('releases/mac-launch-20261027/compact-ext4.py', generic)
        self.assertIn('m.compact(', generic)
        self.assertNotIn('> /w/compaction.json', generic)  # fsck stdout is not JSON
        self.assertIn('write_text(json.dumps(r,indent=2))', generic)
        self.assertNotIn('zerofree /w/rootfs.img', generic)
        self.assertIn('sum(os.path.getsize(p) for p in files)', generic)
        self.assertGreaterEqual(module.REQUIRED, 2 * module.MAX_ROOTFS + module.RESERVE)


if __name__ == '__main__':
    unittest.main()
