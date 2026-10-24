import importlib.util
import unittest
from test_guest_abi import MAC

spec = importlib.util.spec_from_file_location('matrix', MAC / 'Tests/update_arch_v2_matrix.py')
assert spec and spec.loader
matrix = importlib.util.module_from_spec(spec); spec.loader.exec_module(matrix)


class MatrixContract(unittest.TestCase):
    def test_complete_matrix_plan(self):
        rows = matrix.cases([{'id': '0.7.0'}, {'id': '0.7.1'}])
        fresh = {(r['app'], r['image']) for r in rows if r['kind'] == 'fresh'}
        self.assertEqual(fresh, {('N-1', 'N-1'), ('N-1', 'N'), ('N', 'N-1'), ('N', 'N')})
        self.assertEqual({r['kind'] for r in rows}, {'fresh', 'published', 'aged-disk', 'interrupt-mid-apply', 'rollback'})
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({r['id'] for r in rows}), len(rows))
        self.assertEqual(len(matrix.cases([{'id': str(i)} for i in range(5)])), 12)

    def test_execution_is_locked_and_evidence_gated(self):
        source = (MAC / 'Tests/update_arch_v2_matrix.py').read_text()
        for marker in ("'/usr/bin/lockf', '-k', LOCK", "platform.system() != 'Darwin'", "'.wizard-update-matrix'",
                       "support.resolve() != data", "exist_ok=False", "'appsBefore'", "'guest-rolled-back'",
                       "sha(evidence / 'restored-stopped.img')", "'published': False", "'complete': False"):
            self.assertIn(marker, source)
        self.assertNotIn('wizard_heavy_submit', source)
        self.assertNotIn('xcodebuild', source)


if __name__ == '__main__':
    unittest.main()
