#!/usr/bin/env python3
"""Exercise the production installer helper without running a migration."""
import ast
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / 'upgrade-mvp-stack.py'
nodes: list[ast.stmt] = [n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in ('reject_symlink_components', 'install_public_package')]
from typing import Any
namespace: dict[str, Any] = {'os': os, 'shutil': shutil}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
install = namespace['install_public_package']

class PackagePermissions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root/'payload'; self.src.mkdir(mode=0o700)
        self.dst = self.root/'installed'; self.dst.mkdir()
        (self.src/'sub').mkdir(mode=0o700)
        self.module = self.src/'sub'/'managed_runtime.py'
        self.module.write_text('VALUE = 42\n'); self.module.chmod(0o600)
    def test_private_transport_becomes_readable_code(self):
        install(self.src, self.dst)
        for p in [self.dst, self.dst/'sub']:
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o755)
        p = self.dst/'sub'/'managed_runtime.py'
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o644)
        values = {}; exec(compile(p.read_text(), str(p), 'exec'), values)
        self.assertEqual(values['VALUE'], 42)
        self.assertEqual(stat.S_IMODE(self.module.stat().st_mode), 0o600)
    def test_preserves_unrelated_private_file_and_executable(self):
        private = self.dst/'private'; private.write_text('fixture'); private.chmod(0o600)
        tool = self.src/'tool'; tool.write_text('#!/bin/sh\nexit 0\n'); tool.chmod(0o700)
        install(self.src, self.dst); install(self.src, self.dst)
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        self.assertEqual(private.read_text(), 'fixture')
        self.assertEqual(stat.S_IMODE((self.dst/'tool').stat().st_mode), 0o755)
    def test_source_symlink_refused_before_copy(self):
        (self.src/'link').symlink_to(self.module)
        with self.assertRaisesRegex(RuntimeError, 'symlink'): install(self.src, self.dst)
        self.assertFalse((self.dst/'sub').exists())
    def test_source_ancestor_symlink_refused_before_copy(self):
        alias = self.root/'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'symlink'): install(alias/'payload', self.dst)
        self.assertEqual(list(self.dst.iterdir()), [])
        self.assertEqual(stat.S_IMODE(self.module.stat().st_mode), 0o600)
    def test_destination_ancestor_symlink_preserves_outside_bytes_and_modes(self):
        outside = self.root/'outside'; outside.mkdir()
        target = outside/'installed'; target.mkdir(mode=0o700)
        private = target/'private'; private.write_text('fixture'); private.chmod(0o600)
        alias = self.root/'alias'; alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'symlink'): install(self.src, alias/'installed')
        self.assertEqual(private.read_text(), 'fixture')
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
        self.assertFalse((target/'sub').exists())
    def test_destination_symlink_refused_before_copy(self):
        outside = self.root/'outside'; outside.mkdir()
        (self.dst/'sub').symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'symlink'): install(self.src, self.dst)
        self.assertEqual(list(outside.iterdir()), [])

if __name__ == '__main__': unittest.main()
