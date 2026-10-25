"""Factory install copies overlay modes as-is (no chmod pass), so every tool the
upgrade path forces executable must already be executable in the source tree.
Regression: the factory trial died with PermissionError on wizard-runtime-configure."""
import os, re, stat, unittest
from pathlib import Path

GUEST = Path(__file__).resolve().parents[1]
BIN = GUEST / 'overlay/opt/wizard/bin'


class OverlayToolModes(unittest.TestCase):
    def test_upgrade_forced_tools_are_executable_in_source(self):
        text = (GUEST / 'upgrade-mvp-stack.py').read_text()
        match = re.search(r"for tool in \(([^)]*)\):\s*\n\s*if Path\('/opt/wizard/bin',tool\)", text)
        self.assertIsNotNone(match, 'upgrade chmod list moved; update this test')
        tools = re.findall(r"'([^']+)'", match.group(1))
        self.assertIn('wizard-runtime-configure', tools)
        for tool in tools:
            path = BIN / tool
            if path.is_file():
                self.assertTrue(path.stat().st_mode & stat.S_IXUSR, tool + ' is not executable in source')

    def test_directly_executed_tools_are_executable(self):
        for script in (GUEST / 'releases').rglob('guest-apply.py'):
            for tool in set(re.findall(r"run\(\['/opt/wizard/bin/([\w-]+)'", script.read_text())):
                path = BIN / tool
                if path.is_file():
                    self.assertTrue(path.stat().st_mode & stat.S_IXUSR, tool + ' run directly by ' + script.name)


if __name__ == '__main__':
    unittest.main()
