"""Small offline packer source regressions; no mount/root/image build."""
import hashlib
import importlib.util
import io
import json
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
        self.assertNotIn('zerofree /w/rootfs.img', generic)
        self.assertIn('sum(os.path.getsize(p) for p in files)', generic)
        self.assertGreaterEqual(module.REQUIRED, 2 * module.MAX_ROOTFS + module.RESERVE)


if __name__ == '__main__':
    unittest.main()
