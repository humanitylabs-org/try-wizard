#!/usr/bin/env python3
"""An upgrade never touches ~/Documents at startup (try-wizard#109).

Builds before this fix saved ~/Documents/Wizard MVP into files-folder.json by themselves at first run (no marker),
and the Host mounted it at every VM boot, so macOS asked "would like to access files in your Documents folder" at
every launch. The behaviour test compiles the real Shared sources with the Host's unchanged boot-time files-share
block (Virtualization replaced by spies), seeds files-folder.json exactly as the old build wrote it in a fixture
home, and checks nothing is shared or created. It needs macOS (CI runs it); the source checks run everywhere.
"""
import os
import platform
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def host_files_share_block(src):
    """The Host's `if let folder = WizardShared.<x> { ... } [else ...]` files-share block, verbatim."""
    start = src.index('        if let folder = WizardShared.')
    i = start
    while True:
        i = src.index('{', i)
        depth = 0
        while True:
            ch = src[i]
            depth += ch == '{'
            depth -= ch == '}'
            i += 1
            if depth == 0:
                break
        rest = src[i:]
        if not rest.lstrip(' ').startswith('else'):
            return src[start:i]


def host_shared_sources():
    """The Shared files the Host binary is built from (build.sh), so the fixture links the same code."""
    line = next(l for l in (MAC / 'build.sh').read_text().splitlines() if 'Host/main.swift' in l and 'SWIFTC' in l)
    return [MAC / p for p in re.findall(r'Shared/\w+\.swift', line)]


class SourceContracts(unittest.TestCase):
    def test_host_mounts_only_the_active_share(self):
        host = (MAC / 'Host/main.swift').read_text()
        block = host_files_share_block(host)
        self.assertIn('if let folder = WizardShared.activeSharedFolder {', block)
        self.assertIn('VZSharedDirectory', block)
        self.assertNotIn('WizardShared.filesFolder', host)

    def test_finder_and_blocked_message_use_the_active_share(self):
        app = (MAC / 'App/main.swift').read_text()
        self.assertIn('if let f = WizardShared.activeSharedFolder { NSWorkspace.shared.open(f) }', app)
        self.assertIn('WizardShared.activeSharedFolder ?? WizardShared.defaultFilesFolder', app)
        self.assertNotIn('if let f = WizardShared.filesFolder {', app)

    def test_explicit_marker_written_and_file_never_removed(self):
        shared = (MAC / 'Shared/Shared.swift').read_text()
        self.assertIn('["path": url.path, "explicit": true]', shared)
        for src in ('Shared/Shared.swift', 'Host/main.swift', 'App/main.swift'):
            text = (MAC / src).read_text()
            self.assertNotRegex(text, r'removeItem\(at: (WizardShared\.)?filesFolderFile')


@unittest.skipUnless(platform.system() == 'Darwin', 'compiles Swift; runs on the macOS CI runner')
class HostBootBehaviour(unittest.TestCase):
    def test_legacy_share_is_not_touched_and_explicit_share_is_mounted(self):
        work = Path(os.environ.get('WIZARD_WORK_ROOT') or tempfile.gettempdir()).resolve()
        work.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix='legacy-documents-share-', dir=work))
        block = host_files_share_block((MAC / 'Host/main.swift').read_text())
        template = (MAC / 'Tests/LegacyDocumentsShare/main.swift').read_text()
        self.assertIn('    // HOST_FILES_SHARE\n', template)
        (out / 'main.swift').write_text(template.replace('    // HOST_FILES_SHARE\n', block + '\n'))
        sources = host_shared_sources()
        self.assertIn(MAC / 'Shared/Shared.swift', sources)
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-module-cache-path', str(out / 'module-cache'),
                        *map(str, sources), str(out / 'main.swift'), '-o', str(out / 'probe')], check=True)
        fixture = out / 'fixture'
        fixture.mkdir()
        r = subprocess.run([str(out / 'probe'), str(fixture)], capture_output=True, text=True, timeout=60)
        print(r.stdout + r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('LEGACY_DOCUMENTS_SHARE_PASS', r.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
