#!/usr/bin/env python3
"""Mac release pipeline contracts (try-wizard#102). Runs on Linux or macOS, no network."""
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/release.yml'
FETCH = ROOT / 'next/mac/tools/fetch-guest-payload.py'


def job(text, name):
    """Return the text of one top-level job in the workflow."""
    body = text.split('\njobs:\n', 1)[1]
    parts = re.split(r'\n  (?=[a-z][a-z0-9_-]*:\n)', '\n' + body)
    for part in parts:
        if part.startswith(name + ':\n'):
            return part
    raise AssertionError(f'job {name} missing')


class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_github_hosted_only(self):
        self.assertNotIn('self-hosted', self.text)
        self.assertNotIn('forum', self.text)
        self.assertNotIn('thales', self.text.lower())
        runners = re.findall(r'runs-on:\s*(\S+)', self.text)
        self.assertEqual(sorted(set(runners)), ['macos-15', 'ubuntu-24.04'])

    def test_builds_next_mac_not_old_app(self):
        self.assertIn('next/mac/build.sh', self.text)
        self.assertNotIn('macos/build-app.sh', self.text)

    def test_actions_pinned_by_full_sha(self):
        uses = re.findall(r'uses:\s*(\S+)', self.text)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r'^actions/(checkout|upload-artifact|download-artifact)@[0-9a-f]{40}$')

    def test_build_job_has_no_secrets_or_environment(self):
        build = job(self.text, 'build')
        self.assertNotIn('secrets.', build)
        self.assertNotIn('environment:', build)

    def test_sign_job_runs_no_project_code(self):
        sign = job(self.text, 'sign')
        self.assertIn('environment: mac-sign', sign)
        self.assertIn('secrets.SPARKLE_ED25519_KEY', sign)
        self.assertNotIn('actions/checkout', sign)
        self.assertNotIn('next/', sign)
        self.assertIn("github.ref == 'refs/heads/main'", sign)
        self.assertIn('shasum -a 256 -c', sign)  # Sparkle checksum
        self.assertIn('--ed-key-file -', sign)    # key never written to disk

    def test_publish_job_runs_no_project_code(self):
        publish = job(self.text, 'publish')
        self.assertIn('environment: mac-publish', publish)
        for name in ('R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET'):
            self.assertIn('secrets.' + name, publish)
        self.assertNotIn('actions/checkout', publish)
        self.assertNotIn('next/', publish)
        self.assertIn("needs.sign.outputs.signed == 'true'", publish)
        self.assertIn('--immutable', publish)
        # Feed goes last.
        self.assertLess(publish.index('Wizard-$VERSION.dmg:'), publish.index('$PREFIX/appcast.xml"'))

    def test_secrets_only_in_environment_jobs(self):
        names = set(re.findall(r'secrets\.([A-Z0-9_]+)', self.text))
        self.assertEqual(names, {'SPARKLE_ED25519_KEY', 'R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID',
                                 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET'})
        self.assertEqual(set(re.findall(r'secrets\.([A-Z0-9_]+)', job(self.text, 'sign'))), {'SPARKLE_ED25519_KEY'})
        self.assertNotIn('SPARKLE_ED25519_KEY', job(self.text, 'publish'))

    def test_codeowners_cover_pipeline(self):
        owners = (ROOT / '.github/CODEOWNERS').read_text()
        for path in ('/.github/**', '/.github/CODEOWNERS', '/next/mac/tools/make-update-feed.py',
                     '/next/mac/tools/fetch-guest-payload.py', '/next/mac/build.sh'):
            self.assertRegex(owners, re.escape(path) + r'\s+@jdefleur')


class FetchGuestPayload(unittest.TestCase):
    def make_archive(self, directory, files, extra=None):
        prefix = 'Contents/Resources/GuestUpdate/'
        manifest = {'build': '308', 'releaseID': 'x', 'guestPatch': 'mac-stack-v1',
                    'files': {prefix + k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
        path = Path(directory) / 'Wizard-308.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('Wizard.app/Contents/Resources/wizard-release.json', json.dumps(manifest))
            for name, data in {**files, **(extra or {})}.items():
                info = zipfile.ZipInfo('Wizard.app/' + prefix + name)
                info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
                z.writestr(info, data)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def run_fetch(self, archive, digest, out):
        return subprocess.run([sys.executable, str(FETCH), '--url', 'https://example.invalid/a.zip',
                               '--sha256', digest, '--output', str(out), '--archive', str(archive)],
                              capture_output=True, text=True)

    def test_extracts_verified_payload_with_modes(self):
        with tempfile.TemporaryDirectory() as d:
            files = {'wizard-shell.tar': b'image', 'overlay/opt/wizard/bin/run.sh': b'#!/bin/sh\n'}
            archive, digest = self.make_archive(d, files)
            result = self.run_fetch(archive, digest, Path(d) / 'out')
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt['files'], 2)
            self.assertEqual((Path(d) / 'out/wizard-shell.tar').read_bytes(), b'image')
            self.assertTrue((Path(d) / 'out/overlay/opt/wizard/bin/run.sh').stat().st_mode & 0o111)

    def test_rejects_wrong_archive_hash(self):
        with tempfile.TemporaryDirectory() as d:
            archive, _ = self.make_archive(d, {'a': b'1'})
            result = self.run_fetch(archive, '0' * 64, Path(d) / 'out')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SHA-256 mismatch', result.stderr)

    def test_rejects_file_not_in_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            archive, digest = self.make_archive(d, {'a': b'1'}, extra={'b': b'2'})
            result = self.run_fetch(archive, digest, Path(d) / 'out')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('not in release manifest', result.stderr)


if __name__ == '__main__':
    unittest.main()
