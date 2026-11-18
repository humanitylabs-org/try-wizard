#!/usr/bin/env python3
"""The Mac release workflow builds next/mac (the app people run) on GitHub-hosted runners, keeps the Sparkle key in a
signing job that runs no project code, and publishes from a separate job (try-wizard#102, wizard-os#680)."""
import base64
import importlib.util
import json
import re
import unittest
import xml.etree.ElementTree as X
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/release.yml'
PIN = re.compile(r'^[\w.-]+/[\w.-]+@[0-9a-f]{40}(\s+#.*)?$')


def jobs():
    """Split the workflow's jobs by their two-space-indented names (no YAML module needed on CI)."""
    text = WORKFLOW.read_text()
    body = text.split('\njobs:\n', 1)[1]
    parts = re.split(r'(?m)^  ([a-z][\w-]*):\n', body)
    return dict(zip(parts[1::2], parts[2::2]))


def stage_module():
    spec = importlib.util.spec_from_file_location('stage_release', ROOT / 'next/mac/tools/stage-release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseWorkflow(unittest.TestCase):
    def test_builds_next_mac_not_the_old_app(self):
        text = WORKFLOW.read_text()
        self.assertIn('next/mac/build.sh', text)
        self.assertNotIn('macos/build-app.sh', text)
        self.assertNotIn('make runtime', text)

    def test_github_hosted_runners_only(self):
        text = WORKFLOW.read_text()
        self.assertNotIn('self-hosted', text)
        for runner in re.findall(r'runs-on:\s*(.+)', text):
            self.assertIn(runner.strip(), ('macos-15', 'ubuntu-latest'))

    def test_every_action_is_pinned_by_sha(self):
        for use in re.findall(r'uses:\s*(.+)', WORKFLOW.read_text()):
            self.assertRegex(use.strip(), PIN)

    def test_build_job_has_no_secrets_or_environment(self):
        build = jobs()['build']
        self.assertNotIn('secrets.', build)
        self.assertNotIn('environment:', build)

    def test_sign_job_holds_only_the_sparkle_key_and_runs_no_project_code(self):
        sign = jobs()['sign']
        self.assertIn('environment: mac-sign', sign)
        self.assertEqual(set(re.findall(r'secrets\.(\w+)', sign)), {'SPARKLE_ED_PRIVATE_KEY'})
        self.assertNotIn('actions/checkout', sign)
        self.assertNotIn('next/', sign)
        self.assertNotIn('python', sign)
        uses = {u.split('@')[0] for u in re.findall(r'uses:\s*(\S+)', sign)}
        self.assertEqual(uses, {'actions/download-artifact', 'actions/upload-artifact'})
        self.assertIn('shasum -a 256 -c', sign)
        self.assertIn('--ed-key-file -', sign)

    def test_publish_job_holds_only_the_r2_credentials_and_runs_no_project_code(self):
        publish = jobs()['publish']
        self.assertIn('environment: mac-publish', publish)
        self.assertEqual(set(re.findall(r'secrets\.(\w+)', publish)), {'R2_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'})
        self.assertNotIn('actions/checkout', publish)
        self.assertNotIn('next/', publish)
        # Versioned files first, the feed and landing page last.
        self.assertLess(publish.index('application/zip'), publish.index('signed/appcast.xml application/xml'))
        self.assertLess(publish.index('application/x-apple-diskimage'), publish.index('put index.html'))

    def test_only_main_releases_and_tags_are_written_by_the_workflow(self):
        text = WORKFLOW.read_text()
        self.assertIn("refs/heads/main", text)
        self.assertNotIn("tags:\n", text.split('\njobs:\n', 1)[0])
        tag = jobs()['tag']
        self.assertNotIn('secrets.', tag)
        self.assertNotIn('environment:', tag)

    def test_sparkle_is_the_verified_upstream_release(self):
        pinned = re.search(r"SPARKLE_SHA256:\s*([0-9a-f]{64})", WORKFLOW.read_text()).group(1)
        self.assertIn(pinned, (ROOT / 'next/mac/UPDATER.md').read_text())

    def test_release_inputs(self):
        version = json.loads((ROOT / 'next/mac/release/version.json').read_text())
        self.assertRegex(version['version'], r'^\d+\.\d+\.\d+$')
        self.assertIsInstance(version['build'], int)
        self.assertGreater(version['build'], 309)  # 309 (0.7.2) is already on downloads.aiwizards.com
        key = (ROOT / 'next/mac/release/sparkle-public-key.txt').read_text().strip()
        self.assertEqual(len(base64.b64decode(key, validate=True)), 32)

    def test_release_pipeline_is_code_owned(self):
        owners = (ROOT / '.github/CODEOWNERS').read_text()
        for path in ('/.github/', '/next/mac/tools/stage-release.py', '/next/mac/tools/make-update-feed.py',
                     '/next/mac/release/sparkle-public-key.txt'):
            self.assertRegex(owners, r'(?m)^' + re.escape(path) + r'\s+@\w')


class StageRelease(unittest.TestCase):
    def test_appcast_template_has_one_signature_placeholder(self):
        stage = stage_module()
        manifest = {'build': '310', 'arch': 'arm64', 'hostProtocol': 1, 'files': {}, 'guestPatch': None}
        text = stage.appcast_template('0.8.0', 310, manifest, 'https://downloads.example/mac/310/Wizard-310.zip', 1234)
        self.assertEqual(text.count(stage.PLACEHOLDER), 1)
        rss = X.fromstring(text.replace(stage.PLACEHOLDER, 'A' * 86 + '==').split('\n', 1)[1])
        ns = {'s': stage.SPARKLE_NS, 'w': stage.WIZARD_NS}
        item = rss.find('channel/item')
        self.assertEqual(item.find('s:version', ns).text, '310')
        self.assertEqual(item.find('s:shortVersionString', ns).text, '0.8.0')
        self.assertEqual(json.loads(item.find('w:contract', ns).text), manifest)
        enclosure = item.find('enclosure')
        self.assertEqual(enclosure.get('url'), 'https://downloads.example/mac/310/Wizard-310.zip')
        self.assertEqual(enclosure.get('length'), '1234')

    def test_landing_page_names_the_new_dmg(self):
        page = stage_module().landing_page('0.8.0', 310, 'https://downloads.example/mac/310/Wizard-0.8.0.dmg',
                                           25_000_000, 'ab' * 32)
        self.assertIn('href="https://downloads.example/mac/310/Wizard-0.8.0.dmg"', page)
        self.assertIn('WizardOS 0.8.0', page)
        self.assertIn('build 310', page)
        self.assertIn('ab' * 32, page)


if __name__ == '__main__':
    unittest.main()
