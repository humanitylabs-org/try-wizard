"""Regress owner-write preparation of the disposable Sparkle signing copy."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

BUILD = Path(__file__).resolve().parents[1] / 'build.sh'
COMMAND = '/bin/chmod -R u+w "$APP/Contents/Frameworks/Sparkle.framework"'


class SigningCopyTests(unittest.TestCase):
    def test_sealed_copy_only(self):
        recipe = BUILD.read_text()
        copy = 'ditto "$SPARKLE_DIR/Sparkle.framework" "$APP/Contents/Frameworks/Sparkle.framework"'
        self.assertIn(COMMAND, recipe)
        self.assertLess(recipe.index(copy), recipe.index(COMMAND))
        self.assertLess(recipe.index(COMMAND), recipe.index('codesign --force'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'sealed/Sparkle.framework'
            binary = source / 'Versions/B/XPCServices/Downloader.xpc/Contents/MacOS/Downloader'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'fixture executable')
            resource = source / 'Versions/B/resource'
            resource.write_bytes(b'fixture resource')
            (source / 'Versions/Current').symlink_to('B')
            external = root / 'outside'
            external.write_bytes(b'not owned output')
            external.chmod(0o444)
            (source / 'external').symlink_to(external)
            binary.chmod(0o555)
            resource.chmod(0o444)
            for p in sorted(source.rglob('*'), reverse=True):
                if p.is_dir() and not p.is_symlink():
                    p.chmod(0o555)
            source.chmod(0o555)
            before = {str(p.relative_to(source)): (stat.S_IMODE(p.lstat().st_mode), p.read_bytes())
                      for p in source.rglob('*') if p.is_file() and not p.is_symlink()}
            app = root / 'owned-output/Wizard.app'
            output = app / 'Contents/Frameworks/Sparkle.framework'
            output.parent.mkdir(parents=True)
            shutil.copytree(source, output, symlinks=True)
            try:
                subprocess.run(['/bin/bash', '-c', COMMAND], env={**os.environ, 'APP': str(app)}, check=True)
                self.assertEqual(stat.S_IMODE((output / binary.relative_to(source)).stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((output / resource.relative_to(source)).stat().st_mode), 0o644)
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE(external.stat().st_mode), 0o444)
                self.assertEqual(external.read_bytes(), b'not owned output')
                self.assertEqual(before, {str(p.relative_to(source)): (stat.S_IMODE(p.lstat().st_mode), p.read_bytes())
                                          for p in source.rglob('*') if p.is_file() and not p.is_symlink()})
            finally:
                # Test-owned fixture only; allow cleanup of its sealed directories.
                for p in source.rglob('*'):
                    if p.is_dir() and not p.is_symlink():
                        p.chmod(0o755)
                source.chmod(0o755)


if __name__ == '__main__':
    unittest.main()
