#!/usr/bin/env python3
"""Control-plane tests: admission denies stale/incomplete launch inputs."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("launch_audit", ROOT / "audit.py")
assert spec is not None and spec.loader is not None
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "pins.json").read_text())

    def test_actual_inputs_are_blocked_without_build(self):
        result = subprocess.run([sys.executable, str(ROOT / "audit.py")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "blocked")
        self.assertFalse(receipt["buildStarted"])
        self.assertFalse(receipt["publishing"])
        self.assertGreater(len(receipt["blockers"]), 0)

    def test_open_source_gates_are_not_hidden(self):
        errors = audit.inspect(self.manifest, None)
        for key in ["service-integration", "wam-release", "phone-source", "recorder", "pin-consumers", "live-shell-parity"]:
            self.assertIn("open gate: " + key, errors)

    def test_queue_must_cover_every_snapshot_entry(self):
        changed = copy.deepcopy(self.manifest)
        changed["queue"]["entryCount"] += 1
        self.assertIn("queue coverage count mismatch", audit.inspect(changed, None))

    def test_stable_manifest_bytes_are_immutable(self):
        changed = copy.deepcopy(self.manifest)
        changed["stable"]["sha256"] = "0" * 64
        self.assertIn("stable release snapshot digest mismatch", audit.inspect(changed, None))

    def test_unpinned_native_is_not_accepted_as_main(self):
        changed = copy.deepcopy(self.manifest)
        changed["finalPins"]["native"] = "main"
        self.assertIn("unresolved final pin: native", audit.inspect(changed, None))

    def test_partial_factory_recipe_cannot_be_admitted(self):
        errors = audit.inspect(self.manifest, None)
        self.assertIn("reviewed complete assembly recipe is not pinned", errors)

    def test_all_input_shas_have_exact_git_identity(self):
        for name, source in self.manifest["sourceInputs"].items():
            with self.subTest(source=name):
                self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
