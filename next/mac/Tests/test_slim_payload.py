"""Source-only lossless migration-payload regressions; no Docker or VM."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('slim_payload', HERE / 'tools/compress-guest-payload.py')
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class SlimPayloadTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'source'
        source.mkdir()
        self.archives = {'wizard-shell.tar': b'shell archive\0' * 1000,
                         'wizard-hermes-managed.tar': b'security-patched image\0' * 1000}
        for name, data in self.archives.items():
            (source / name).write_bytes(data)
        (source / 'source-pins.json').write_text('{"source":"unchanged-pin"}')
        bom = {'schema': 1, 'payload_sha256': digest(self.archives['wizard-shell.tar']),
               'payload_bytes': len(self.archives['wizard-shell.tar']),
               'service_image_id': 'sha256:service-unchanged',
               'managed_runtime': {'archive': 'wizard-hermes-managed.tar', 'image': 'sha256:managed-unchanged',
                                   'stock': 'stock-unchanged', 'bytes': len(self.archives['wizard-hermes-managed.tar']),
                                   'sha256': digest(self.archives['wizard-hermes-managed.tar'])},
               'files': {name: digest((source / name).read_bytes()) for name in [*self.archives, 'source-pins.json']}}
        (source / 'runtime-bom.json').write_text(json.dumps(bom))
        return source, bom

    def test_smaller_without_changing_image_bytes_identity_or_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, before = self.fixture(root)
            original = {p.name: p.read_bytes() for p in source.iterdir()}
            receipt = module.compress(source, root / 'slim')
            after = json.loads((root / 'slim/runtime-bom.json').read_text())
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, original)
            for name, data in self.archives.items():
                packed = (root / 'slim' / name).read_bytes()
                self.assertEqual(gzip.decompress(packed), data)
                self.assertLess(len(packed), len(data))
                self.assertEqual(after['files'][name], digest(packed))
            self.assertEqual(after['service_image_id'], before['service_image_id'])
            for key in ('stock', 'image', 'archive'):
                self.assertEqual(after['managed_runtime'][key], before['managed_runtime'][key])
            self.assertTrue(receipt['decodedBytesVerified'])
            self.assertEqual((root / 'slim/source-pins.json').read_bytes(), original['source-pins.json'])
            self.assertEqual(after['payload_sha256'], after['files']['wizard-shell.tar'])
            self.assertEqual(after['managed_runtime']['sha256'], after['files']['wizard-hermes-managed.tar'])

    def test_bad_digest_or_symlink_refused_before_output(self):
        for kind in ('digest', 'symlink', 'escape'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                source, bom = self.fixture(root)
                if kind == 'digest':
                    (source / 'wizard-shell.tar').write_bytes(b'changed')
                elif kind == 'symlink':
                    (source / 'link').symlink_to(source / 'source-pins.json')
                else:
                    bom['files']['../outside'] = '0' * 64
                    (source / 'runtime-bom.json').write_text(json.dumps(bom))
                with self.assertRaises((ValueError, FileNotFoundError)):
                    module.compress(source, root / 'slim')
                self.assertFalse((root / 'slim').exists())

    def test_existing_output_and_nested_output_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, _ = self.fixture(root)
            for output in (source, source / 'nested'):
                with self.assertRaises(ValueError):
                    module.compress(source, output)

    def test_already_gzip_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, _ = self.fixture(root)
            module.compress(source, root / 'one')
            module.compress(root / 'one', root / 'two')
            for name in self.archives:
                self.assertEqual((root / 'one' / name).read_bytes(), (root / 'two' / name).read_bytes())

    def test_existing_consumers_keep_exact_load_paths_and_integrity(self):
        guest = HERE.parent / 'guest'
        upgrade = (guest / 'upgrade-mvp-stack.py').read_text()
        self.assertIn("['docker','load','-i',str(a.payload/'wizard-shell.tar')]", upgrade)
        self.assertIn("['docker','load','-i',str(a.payload/'wizard-hermes-managed.tar')]", upgrade)
        self.assertIn("bom['payload_sha256']", upgrade)
        self.assertIn("managed['sha256']", upgrade)
        self.assertIn('compress-guest-payload.py', (HERE / 'build.sh').read_text())


if __name__ == '__main__':
    unittest.main()
