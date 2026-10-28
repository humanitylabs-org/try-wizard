#!/usr/bin/env python3
"""An app update installs every file the front door needs.

upgrade-mvp-stack.py copies only the overlay paths it names. setup/server.py loads sibling modules from its own
folder (Path(__file__).with_name(...)); one missing from the list leaves an updated Mac with the new server.py and
without the module, and the front door (onboarding, backup) fails to start."""
import ast, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUEST = ROOT / 'next/guest'
SETUP = GUEST / 'overlay/opt/wizard/setup'


def installed_paths():
    tree = ast.parse((GUEST / 'upgrade-mvp-stack.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id == 'rel' \
                and isinstance(node.iter, ast.Tuple):
            return {elt.value for elt in node.iter.elts}
    raise AssertionError('no `for rel in (...)` install list in upgrade-mvp-stack.py')


class UpgradeInstallsFrontDoor(unittest.TestCase):
    def test_every_module_server_py_loads_is_installed(self):
        names = set(re.findall(r'with_name\(\s*["\']([^"\']+)["\']\s*\)', (SETUP / 'server.py').read_text()))
        self.assertIn('backup_frontdoor.py', names)
        missing = sorted(n for n in names if (SETUP / n).exists() and f'setup/{n}' not in installed_paths())
        self.assertEqual(missing, [], 'server.py loads these, but an update does not install them')

    def test_every_python_file_in_setup_is_installed(self):
        missing = sorted(p.name for p in SETUP.glob('*.py') if f'setup/{p.name}' not in installed_paths())
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
