"""Evaluate the actual non-preflight result assignment; no VM/clone/archive work."""
import ast
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import symtable
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]/'qa/voice-installer-diagnostic-thales.py'

def undefined_globals(text):
    """Audit every lexical scope, not just the exercised dictionary expression."""
    root = symtable.symtable(text, str(SOURCE), 'exec')
    bound = {s.get_name() for s in root.get_symbols()
             if s.is_assigned() or s.is_imported() or s.is_namespace()}
    allowed = bound | set(dir(builtins)) | {'__file__', '__name__'}
    missing = set()
    def visit(scope):
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in allowed:
                missing.add(symbol.get_name())
        for child in scope.get_children():
            visit(child)
    visit(root)
    return missing

def result_assignment(text):
    tree = ast.parse(text)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    assignments = [n for n in main.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'result' for t in n.targets)]
    assert len(assignments) == 1
    return ast.Module(body=[assignments[0]], type_ignores=[])

class ResultConstructionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('diagnostic_result_runner', SOURCE)
        assert spec is not None and spec.loader is not None
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR', str(Path.cwd())))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(self.runner, 'HERE', self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        def save(path, obj):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(obj))
        self.stage = {'sourceRevisions': {'synthetic': 'only'}, 'qaSourceRevision': 'synthetic-qa',
                      'recoveryStageSha256': 'synthetic-stage', 'recoveryRoot': str(self.root/'secured'),
                      'inheritedSourceStageSha256': 'synthetic-source', 'recoveryRequestSha256': 'synthetic-request'}
        package = self.root/'secured/recovery-evidence'
        source = package/'voice-package'
        source.mkdir(parents=True)
        save(source/'resolved-files.json', {})
        receipt = self.root/'image-receipt.json'; save(receipt, {'synthetic': True})
        self.stage['recoveryImageReceipt'] = str(receipt)
        self.proof_path = package/'result.json'
        save(self.proof_path, {'success': True, 'source': self.stage['sourceRevisions'],
             'sourceStageSha256': 'synthetic-source', 'requestSha256': 'synthetic-request',
             'imageReceipt': str(receipt), 'imageReceiptSha256': self.digest(receipt),
             'resolvedFilesSha256': self.digest(source/'resolved-files.json')})
        log = self.root/'native.log'; log.write_bytes(b'synthetic no-VM fixture\n')
        job = 'heavy_'+'0'*32
        native = self.root/'native.json'
        save(native, {'job_id': job, 'state': 'completed', 'exit_code': 0,
                      'log_path': str(log), 'log_sha256': self.digest(log)})
        self.completion = {'parentVerifiedNativeCompleted': True, 'nativeExitCode': 0, 'jobId': job,
             'recoveryStageSha256': 'synthetic-stage', 'nativeReceiptPath': str(native),
             'nativeReceiptSha256': self.digest(native), 'nativeLogPath': str(log),
             'nativeLogSha256': self.digest(log), 'recoveryResultSha256': self.digest(self.proof_path)}
        self.completion_path = self.root/'inputs/recovery-completion.json'
        save(self.completion_path, self.completion)
        self.completion_sha = self.digest(self.completion_path)

    def evaluate_result(self, text):
        completion, proof, source = self.runner.recovery_binding(self.stage, self.completion_sha, full_payload=True)
        scope = dict(vars(self.runner), stage=self.stage,
                     a=SimpleNamespace(stage_sha256='synthetic-seal', recovery_completion_sha256=self.completion_sha),
                     lease={'synthetic': True}, initial={'noVMStarted': True}, completion=completion, proof=proof)
        self.assertNotIn('proof_path', scope)  # It is local to recovery_binding.
        exec(compile(result_assignment(text), str(SOURCE), 'exec'), scope)
        return scope['result']

    def test_actual_nonpreflight_result_evaluates_bound_recovery_hash(self):
        result = self.evaluate_result(SOURCE.read_text())
        self.assertEqual(result['recoveryResultSha256'], self.digest(self.proof_path))
        self.assertEqual(result['recoveryCompletionSha256'], self.completion_sha)
        self.assertEqual(result['recoveryJobId'], self.completion['jobId'])
        for field in ('success', 'diagnosticCompleted', 'fullAcceptance', 'voiceTranscriptionAccepted', 'ownerStateAccess'):
            self.assertIs(result[field], False)
        self.assertIs(result['diagnosticOnly'], True)
        self.assertIs(result['reviewRequired'], True)

    def test_real_binding_still_rejects_recovery_result_drift(self):
        self.proof_path.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'Parent-reviewed recovery result drift'):
            self.evaluate_result(SOURCE.read_text())

    def test_old_nonpreflight_expression_reproduces_nameerror(self):
        text = SOURCE.read_text()
        new = "'recoveryResultSha256':completion['recoveryResultSha256'],'recoveryNativeLogSha256'"
        self.assertEqual(text.count(new), 1)
        old = text.replace(new, "'recoveryResultSha256':sha(proof_path),'recoveryNativeLogSha256'")
        with self.assertRaisesRegex(NameError, 'proof_path'):
            self.evaluate_result(old)
        self.assertEqual(undefined_globals(old), {'proof_path'})

    def test_all_runner_scopes_have_no_undefined_global_peers(self):
        text = SOURCE.read_text()
        self.assertEqual(undefined_globals(text), set())
        self.assertEqual(undefined_globals(text+'\ndef missed_peer():\n    return unbound_peer\n'), {'unbound_peer'})

if __name__ == '__main__':
    unittest.main(verbosity=2)
