#!/usr/bin/env python3
"""Regression guard for tracked source/config/docs; historical receipts are immutable."""
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Keep exceptions path-based: records, never active executable/config directories.
EVIDENCE_PREFIXES = ("docs/evidence/", "ops/evidence/")
HISTORICAL_FILES = ('NATIVE-INTEGRATION.json', 'NATIVE-INTEGRATION.md', 'next/QA-0.2.2.md', 'next/QA-SLIM-0.2.2.md', 'next/mac/QA-FILES-0.6.1.md', 'next/mac/FIRST-INSTALL-ROUTE-GATE.md')
HOST_ALIAS = "tha" + "les"
PATTERNS = (
    re.compile("/Volumes/" + "ThalesMedia"),
    re.compile("/home/" + "telos" + r"(?:/|\b)"),
    re.compile(r"[\w.-]+\." + "tailc0f369" + r"\.ts\.net"),
    re.compile(r"\b(?:ssh|scp|rsync)\b[^\n]*?(?<![\w.-])" + HOST_ALIAS + r"(?=[:\s'\"]|$)"),
    re.compile(r"['\"]" + HOST_ALIAS + r"['\"]"),
    re.compile("/Users/" + HOST_ALIAS + r"(?:/|\b)"),
)


def historical(name):
    return (name.startswith(EVIDENCE_PREFIXES) or name in HISTORICAL_FILES
            or re.fullmatch(r"docs/acceptance/[^/]+/RECEIPT[^/]*", name)
            or re.fullmatch(r"docs/acceptance/[^/]*\d{4}-\d{2}-\d{2}[^/]*\.md", name))


def violations(root):
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    found = []
    for name in filter(None, names):
        if historical(name):
            continue
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                found.append(f"{name}:{number}: {line.strip()}")
    return found


class PortablePathsTests(unittest.TestCase):
    def test_tracked_files_are_portable(self):
        self.assertEqual([], violations(ROOT), "\n" + "\n".join(violations(ROOT)))

    def test_python_work_root_override_and_fallback(self):
        import ast
        import os
        from unittest.mock import patch
        names = subprocess.check_output(["git", "ls-files", "next"], cwd=ROOT).decode().splitlines()
        candidates = [ROOT / n for n in names if n.endswith(".py") and "WORK_ROOT =" in (ROOT / n).read_text()]
        self.assertGreater(len(candidates), 0)
        with tempfile.TemporaryDirectory() as directory:
            for override in [None, str(pathlib.Path(directory) / "work disk")]:
                env = {"TMPDIR": directory}
                if override:
                    env["WIZARD_WORK_ROOT"] = override
                with patch.dict(os.environ, env, clear=True):
                    for path in candidates:
                        tree = ast.parse(path.read_text())
                        nodes = [node for node in tree.body if
                                 isinstance(node, ast.Import) and any(alias.name in ("os", "pathlib") for alias in node.names) or
                                 isinstance(node, ast.ImportFrom) and node.module == "pathlib" or
                                 isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WORK_ROOT" for t in node.targets)]
                        scope = {}
                        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
                        expected = pathlib.Path(override) if override else pathlib.Path(directory) / "wizard-work"
                        self.assertEqual(expected.resolve(), scope["WORK_ROOT"], str(path))

    def test_personal_patterns(self):
        values = ["/Volumes/" + "ThalesMedia/x", "/home/" + "telos/x",
                  "https://wizard." + "tailc0f369" + ".ts.net",
                  "ssh -o BatchMode=yes " + (HOST_ALIAS + " true"), "scp file " + (HOST_ALIAS + ":/x"),
                  "['ssh', '" + HOST_ALIAS + "']", "/Users/" + (HOST_ALIAS + "/work")]
        for value in values:
            with self.subTest(value=value):
                self.assertTrue(any(p.search(value) for p in PATTERNS))

    def test_portable_values(self):
        for value in ['"$WIZARD_WORK_ROOT/build"', 'ssh "$WIZARD_BUILD_HOST"',
                      'tools/thales-build.sh', 'https://wizard.example.ts.net']:
            self.assertFalse(any(p.search(value) for p in PATTERNS), value)

    def test_receipt_allowlist_not_active_code(self):
        self.assertTrue(historical("docs/evidence/run/probe.sh"))
        self.assertTrue(historical("docs/acceptance/router-2026-10-21/RECEIPT.md"))
        self.assertTrue(historical("docs/acceptance/router-2026-10-21.md"))
        self.assertFalse(historical("tools/acceptance/router/run.sh"))
        self.assertFalse(historical("docs/acceptance/README.md"))

    def test_guard_reads_tracked_not_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            value = "/home/" + "telos/private"
            (root / "script.py").write_text("safe\n" + value + "\n")
            (root / "untracked.txt").write_text(value)
            subprocess.run(["git", "add", "script.py"], cwd=root, check=True)
            self.assertEqual(["script.py:2: " + value], violations(root))


if __name__ == "__main__":
    unittest.main()
