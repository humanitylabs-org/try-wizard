#!/usr/bin/env python3
"""The Mac release workflow builds next/mac (the app people run) on GitHub-hosted runners, keeps the Sparkle key in a
signing job that runs no project code, and publishes from a separate job (try-wizard#102, wizard-os#680)."""
import base64
import importlib.util
import json
import os
import re
import subprocess
import tempfile
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

    def test_release_carries_the_code_only_guest_update(self):
        """try-wizard#123: guest fixes reach Macs with the version bump, not only through a new WizardOS disk."""
        build = jobs()['build']
        self.assertIn('next/guest/build-code-payload.py --out "$RUNNER_TEMP/guest-update"', build)
        self.assertIn('export GUEST_UPDATE_PAYLOAD="$RUNNER_TEMP/guest-update"', build)
        self.assertLess(build.index('export GUEST_UPDATE_PAYLOAD'), build.index('next/mac/build.sh'))
        self.assertIn("r['guestPatch'] == 'mac-stack-v1'", build)
        self.assertIn("- 'next/guest/**'", WORKFLOW.read_text().split('\njobs:\n', 1)[0])

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
        self.assertEqual(set(re.findall(r'secrets\.(\w+)', publish)),
                         {'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_SESSION_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'})
        self.assertNotIn('actions/checkout', publish)
        self.assertNotIn('next/', publish)
        self.assertNotIn('uses:', publish.split('Upload versioned files', 1)[1])
        # Versioned files first, then the landing page, the feed last.
        self.assertLess(publish.index('application/zip'), publish.index('put mac/index.html'))
        self.assertLess(publish.index('application/x-apple-diskimage'), publish.index('put mac/index.html'))
        self.assertLess(publish.index('put mac/index.html'), publish.index('signed/appcast.xml application/xml'))

    def test_publish_uses_bucket_scoped_temporary_credentials(self):
        """try-wizard#115: S3 API with a session token, no account-wide API token, every guard kept."""
        publish = jobs()['publish']
        self.assertNotIn('R2_API_TOKEN', publish)
        self.assertNotIn('api.cloudflare.com', publish)
        self.assertIn('AWS_SESSION_TOKEN: ${{ secrets.R2_SESSION_TOKEN }}', publish)
        self.assertIn('https://$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com', publish)
        self.assertIn('AWS_DEFAULT_REGION: auto', publish)
        self.assertIn('R2 temporary credentials in mac-publish expired', publish)
        # Never overwrite a versioned key: HEAD first, then skip (same bytes) or fail.
        self.assertIn('head-object', publish)
        self.assertIn('versioned paths are never overwritten', publish)
        # Read back through the public URL and its checksum.
        self.assertIn('did not read back byte for byte', publish)
        # A write outside mac/ and mac-dryrun/ must be refused before anything is uploaded.
        self.assertIn('grep -q AccessDenied', publish)
        self.assertLess(publish.index('publish-scope-check/'), publish.index('put "$CHANNEL/$BUILD/'))
        # Every key written stays inside the credential's prefixes.
        for key in re.findall(r'(?m)^\s+put (\S+) ', publish):
            self.assertRegex(key, r'^"?(\$CHANNEL|mac)/')
        self.assertIn('[[ "$CHANNEL" == mac || "$CHANNEL" == mac-dryrun ]]', publish)

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


FAKE_GH = r"""#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "api repos/o/r/git/ref/tags/v1.2.3")
    if [[ -n "${GH_TAG_SHA:-}" ]]; then echo "$GH_TAG_SHA"; exit 0; fi
    echo '{"message":"Not Found","documentation_url":"https://docs.github.com/rest/git/refs#get-a-reference","status":"404"}'
    echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;
  "api repos/o/r/git/refs") echo '{}'; exit 0 ;;
  "release view") exit 1 ;;
  "release create") exit 0 ;;
esac
exit 3
"""


class TagStep(unittest.TestCase):
    """Runs the tag job's own script with a fake gh that answers like gh 2.10x does (try-wizard#182)."""

    def run_step(self, tag_sha=''):
        script = re.search(r'(?ms)^        run: \|\n(.*)', jobs()['tag']).group(1)
        script = '\n'.join(line[10:] for line in script.splitlines())
        with tempfile.TemporaryDirectory(prefix='try-wizard-182-') as tmp:
            gh = Path(tmp, 'gh')
            gh.write_text(FAKE_GH)
            gh.chmod(0o755)
            log = Path(tmp, 'gh.log')
            env = dict(os.environ, PATH=f'{tmp}:{os.environ["PATH"]}', GH_LOG=str(log), GH_TAG_SHA=tag_sha,
                       GITHUB_REPOSITORY='o/r', GITHUB_SHA='a' * 40, GITHUB_RUN_ID='1',
                       GITHUB_SERVER_URL='https://github.com', VERSION='1.2.3', BUILD='400',
                       DOWNLOADS='https://downloads.example')
            done = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            return done, (log.read_text() if log.exists() else '')

    def test_missing_tag_is_created_and_released(self):
        done, log = self.run_step()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(f'api repos/o/r/git/refs -f ref=refs/tags/v1.2.3 -f sha={"a" * 40}', log)
        self.assertIn('release create v1.2.3', log)

    def test_tag_at_the_release_commit_passes_without_a_new_tag(self):
        done, log = self.run_step('a' * 40)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn('git/refs -f', log)
        self.assertIn('release create v1.2.3', log)

    def test_tag_at_another_commit_stops(self):
        done, log = self.run_step('b' * 40)
        self.assertEqual(done.returncode, 1)
        self.assertIn('already points at ' + 'b' * 40, done.stdout)
        self.assertNotIn('git/refs -f', log)


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

    # try-wizard#126: releases that need a new download.
    ARGS = ('0.9.0', 330, {'build': '330', 'arch': 'arm64', 'hostProtocol': 1, 'files': {}, 'guestPatch': None},
            'https://downloads.example/mac/330/Wizard-330.zip', 1234)
    # appcast_template('0.9.0', 330, ...) as stage-release.py wrote it before try-wizard#126, byte for byte.
    BEFORE = ('<?xml version="1.0" encoding="utf-8"?>\n<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" '
              'xmlns:wizard="https://humanitylabs.co/wizard-updates/v1" version="2.0"><channel><title>WizardOS updates</title>'
              '<item><title>WizardOS 0.9.0</title><sparkle:version>330</sparkle:version><sparkle:shortVersionString>0.9.0'
              '</sparkle:shortVersionString><sparkle:minimumSystemVersion>14.0.0</sparkle:minimumSystemVersion>'
              '<sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements><wizard:contract>{"arch":"arm64",'
              '"build":"330","files":{},"guestPatch":null,"hostProtocol":1}</wizard:contract><enclosure '
              'url="https://downloads.example/mac/330/Wizard-330.zip" type="application/octet-stream" length="1234" '
              'sparkle:edSignature="@ED_SIGNATURE@" /></item></channel></rss>\n')

    def test_without_manual_below_the_appcast_is_unchanged(self):
        stage = stage_module()
        self.assertEqual(stage.appcast_template(*self.ARGS), self.BEFORE)
        self.assertEqual(stage.appcast_template(*self.ARGS, manual_below=None), self.BEFORE)
        with tempfile.TemporaryDirectory(prefix='try-wizard-126-') as tmp:
            version = Path(tmp, 'version.json')
            version.write_text(json.dumps({'version': '0.9.0', 'build': 330}))
            self.assertIsNone(stage.manual_below(version, 330))
        # The release's own version.json, as committed, sets nothing.
        self.assertIsNone(stage.manual_below(stage.VERSION_FILE, 10 ** 6))

    def test_manual_below_makes_older_installs_download_the_new_dmg(self):
        stage = stage_module()
        text = stage.appcast_template(*self.ARGS, manual_below=328)
        self.assertEqual(text.count(stage.PLACEHOLDER), 1)
        item = X.fromstring(text.split('\n', 1)[1]).find('channel/item')
        ns = {'s': stage.SPARKLE_NS}
        self.assertEqual(item.find('s:informationalUpdate/s:belowVersion', ns).text, '328')
        self.assertEqual(item.find('link').text, 'https://www.aiwizards.com/downloads')
        # Newer installs still update by themselves: the signed enclosure stays.
        self.assertEqual(item.find('enclosure').get('url'), 'https://downloads.example/mac/330/Wizard-330.zip')
        self.assertEqual(item.find('s:version', ns).text, '330')
        # Nothing else in the item moved.
        trimmed = text.replace('<link>https://www.aiwizards.com/downloads</link><sparkle:informationalUpdate>'
                               '<sparkle:belowVersion>328</sparkle:belowVersion></sparkle:informationalUpdate>', '')
        self.assertEqual(trimmed, self.BEFORE)

    def test_manual_below_is_read_from_version_json_and_bounded(self):
        stage = stage_module()
        with tempfile.TemporaryDirectory(prefix='try-wizard-126-') as tmp:
            version = Path(tmp, 'version.json')
            version.write_text(json.dumps({'version': '0.9.0', 'build': 330, 'manualBelow': 330}))
            self.assertEqual(stage.manual_below(version, 330), 330)
            # Above its own build the release would tell its own installs to download it again.
            for bad in (331, 0, -1, '328', True, 328.0):
                version.write_text(json.dumps({'version': '0.9.0', 'build': 330, 'manualBelow': bad}))
                with self.assertRaises(AssertionError, msg=repr(bad)):
                    stage.manual_below(version, 330)

    def test_appcast_with_manual_below_signs_and_verifies(self):
        """sign_update signs the feed's bytes with Ed25519 and appends them in a comment; promote.yml checks that."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            self.skipTest('python cryptography not installed')
        stage = stage_module()
        key = Ed25519PrivateKey.generate()
        archive_sig = base64.b64encode(key.sign(b'archive bytes')).decode()
        body = stage.appcast_template(*self.ARGS, manual_below=328).replace(stage.PLACEHOLDER, archive_sig).encode()
        signature = key.sign(body)
        signed = body + ('<!-- sparkle-signatures:\nedSignature: %s\nlength: %d\n-->\n'
                         % (base64.b64encode(signature).decode(), len(body))).encode()
        sig = re.search(rb'edSignature: (\S+)', signed.split(b'<!-- sparkle-signatures:')[1]).group(1)
        length = int(re.search(rb'length: (\d+)', signed).group(1))
        key.public_key().verify(base64.b64decode(sig), signed[:length])   # raises when it doesn't verify
        X.fromstring(signed[:length].split(b'\n', 1)[1])

    def test_landing_page_names_the_new_dmg(self):
        page = stage_module().landing_page('0.8.0', 310, 'https://downloads.example/mac/310/Wizard-0.8.0.dmg',
                                           25_000_000, 'ab' * 32)
        self.assertIn('href="https://downloads.example/mac/310/Wizard-0.8.0.dmg"', page)
        self.assertIn('WizardOS 0.8.0', page)
        self.assertIn('build 310', page)
        self.assertIn('ab' * 32, page)


if __name__ == '__main__':
    unittest.main()
