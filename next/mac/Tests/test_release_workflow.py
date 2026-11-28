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
        page = 'put "$CHANNEL/index.html"'
        self.assertLess(publish.index('application/zip'), publish.index(page))
        self.assertLess(publish.index('application/x-apple-diskimage'), publish.index(page))
        self.assertLess(publish.index(page), publish.index('put "$CHANNEL/appcast.xml" signed/appcast.xml application/xml'))

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
        self.assertIn('[[ "$CHANNEL" == mac-dryrun || "$CHANNEL" == mac-beta ]]', publish)

    def test_publish_waits_for_the_upgrade_test(self):
        """try-wizard#129: nothing reaches the live feed before upgrade-test passed."""
        publish = jobs()['publish']
        self.assertIn('needs: [build, sign, upgrade-test]', publish)
        condition = publish.split('if: >-', 1)[1].split('runs-on:', 1)[0]
        self.assertIn("needs.upgrade-test.result == 'success'", condition)
        # No way around it: a skipped upgrade test never lets publish run.
        self.assertNotIn("'skipped'", condition)
        self.assertIn("needs.sign.result == 'success'", condition)
        self.assertIn("needs.sign.outputs.signed == 'true'", condition)
        self.assertNotIn('always()', condition)
        self.assertIn('needs: [build, publish]', jobs()['tag'])

    def test_tag_runs_after_a_publish_that_followed_a_skipped_upgrade_test(self):
        """try-wizard#195: an if without a status function gets an implicit success(), false after a skipped job."""
        tag = jobs()['tag']
        condition = re.search(r'(?m)^    if: (.*)$', tag).group(1).strip('"')
        self.assertTrue(condition.startswith('!cancelled() && '), condition)
        self.assertIn("needs.build.outputs.mode == 'release'", condition)
        self.assertIn("needs.publish.result == 'success'", condition)
        self.assertNotIn('always()', condition)

    def test_upgrade_test_runs_both_steps_without_secrets(self):
        test = jobs()['upgrade-test']
        self.assertIn('runs-on: macos-15', test)
        self.assertIn('needs: [build, sign]', test)
        self.assertIn("needs.build.outputs.upgrade == 'yes' && needs.sign.outputs.signed == 'true'", test)
        self.assertNotIn('secrets.', test)
        self.assertNotIn('environment:', test)
        self.assertIn('next/mac/tools/upgrade-test.py run --live-feed "$DOWNLOADS/mac/appcast.xml"', test)
        self.assertIn('--plus-one', test)
        evidence = test.split('Upload the upgrade test', 1)[1]
        self.assertIn('if: failure()', evidence)
        self.assertIn('upgrade-evidence', evidence)

    def test_private_key_appears_only_in_sign(self):
        for name, body in jobs().items():
            if name != 'sign':
                self.assertNotIn('SPARKLE_ED_PRIVATE_KEY', body, name)
                self.assertNotIn('--ed-key-file', body, name)
        head = WORKFLOW.read_text().split('\njobs:\n', 1)[0]
        head = '\n'.join(line for line in head.splitlines() if not line.lstrip().startswith('#'))
        self.assertNotIn('SPARKLE_ED_PRIVATE_KEY', head)
        self.assertNotIn('secrets.', head)

    def test_upgrade_test_runs_on_every_signed_release(self):
        """try-wizard#129 switch-default: no repo variable or Run workflow tick turns the upgrade test off."""
        text = WORKFLOW.read_text()
        self.assertNotIn('WOS_MAC_UPGRADE_TEST', text)
        self.assertNotIn('upgrade_test', text)
        self.assertNotIn('UPGRADE_TEST', text)
        build = jobs()['build']
        self.assertIn('[[ "$mode" != check ]] && upgrade=yes', build)
        # Every upgrade step in build and sign runs only where something is signed (not on pull requests).
        for job in ('build', 'sign'):
            body = jobs()[job]
            for step in re.split(r'(?m)^      - name: ', body)[1:]:
                if 'upgrade' in step.split('\n', 1)[0].lower():
                    self.assertRegex(step, r"if: .*upgrade == 'yes'", step.split('\n', 1)[0])
        sign = jobs()['sign']
        self.assertIn('if [[ "$UPGRADE" == yes ]]; then', sign)

    def test_candidate_plus_one_is_built_unsigned_and_signed_only_in_sign(self):
        build = jobs()['build']
        self.assertIn('BUILD=$plus next/mac/build.sh', build)
        self.assertIn('plus=$((BUILD + 1))', build)
        self.assertIn('--base-url "$UPGRADE_LOOPBACK"', build)
        sign = jobs()['sign']
        self.assertIn('plus_sig=$(sign_update -p "$plus_archive")', sign)
        self.assertIn('sign_update --verify signed-upgrade/appcast-plus-one.xml', sign)
        self.assertIn('sign_update --verify signed-upgrade/appcast-candidate.xml', sign)
        # Never published: publish reads only the mac-stage and mac-signed artifacts.
        publish = jobs()['publish']
        self.assertNotIn('upgrade', publish.split('steps:', 1)[1])

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

    def run_step(self, tag_sha='', channel='mac-beta'):
        script = re.search(r'(?ms)^        run: \|\n(.*)', jobs()['tag']).group(1)
        script = '\n'.join(line[10:] for line in script.splitlines())
        with tempfile.TemporaryDirectory(prefix='try-wizard-182-') as tmp:
            gh = Path(tmp, 'gh')
            gh.write_text(FAKE_GH)
            gh.chmod(0o755)
            log = Path(tmp, 'gh.log')
            env = dict(os.environ, PATH=f'{tmp}:{os.environ["PATH"]}', GH_LOG=str(log), GH_TAG_SHA=tag_sha,
                       GITHUB_REPOSITORY='o/r', GITHUB_SHA='a' * 40, GITHUB_RUN_ID='1',
                       GITHUB_SERVER_URL='https://github.com', VERSION='1.2.3', BUILD='400', CHANNEL=channel,
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

    def test_every_release_is_a_tester_prerelease(self):
        # wizard-os#720 (on for everyone): the GitHub release is a prerelease, never latest, with or without a channel.
        for channel in ('mac-beta', ''):
            done, log = self.run_step(channel=channel)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn('--prerelease --latest=false', log)
            self.assertIn('/mac-beta/400/Wizard-1.2.3.dmg', log)

    def test_tag_at_another_commit_stops(self):
        done, log = self.run_step('b' * 40)
        self.assertEqual(done.returncode, 1)
        self.assertIn('already points at ' + 'b' * 40, done.stdout)
        self.assertNotIn('git/refs -f', log)


PROMOTE = ROOT / '.github/workflows/promote.yml'


def promote_jobs():
    body = PROMOTE.read_text().split('\njobs:\n', 1)[1]
    parts = re.split(r'(?m)^  ([a-z][\w-]*):\n', body)
    return dict(zip(parts[1::2], parts[2::2]))


class ReleaseLanes(unittest.TestCase):
    """wizard-os#720: merges publish tester builds to mac-beta/; the release train promotes one after a 72h soak."""

    def test_tester_lane_is_on_for_everyone(self):
        build = jobs()['build']
        self.assertNotIn('WOS_RELEASE_LANES', WORKFLOW.read_text())
        self.assertIn('channel=$([[ "$mode" == dry-run ]] && echo mac-dryrun || echo mac-beta)', build)
        # The app always reads the public feed, so promoted bytes update installed apps.
        self.assertIn('SPARKLE_FEED="$DOWNLOADS/mac/appcast.xml"', build)

    def test_tester_build_never_writes_mac(self):
        publish = jobs()['publish']
        self.assertNotIn('"$CHANNEL" == mac ]]', publish)
        self.assertNotRegex(publish, r'(?m)^\s+put mac/')
        tester = publish.split('if [[ "$MODE" == release ]]; then\n            # A tester build', 1)[1].split('\n          fi\n', 1)[0]
        keys = re.findall(r'(?m)^\s+put (\S+) ', tester)
        self.assertEqual(len(keys), 3)
        for key in keys:
            self.assertTrue(key.startswith('"$CHANNEL/'), key)
        # Its signed feed and page stay immutable per build, so promotion copies them without signing again.
        self.assertIn('put "$CHANNEL/$BUILD/appcast.xml" signed/appcast.xml application/xml "$immutable" yes', tester)
        self.assertIn('put "$CHANNEL/$BUILD/index.html"', tester)
        self.assertLess(publish.index('put "$CHANNEL/$BUILD/appcast.xml"'), publish.index('put "$CHANNEL/appcast.xml"'))
        self.assertIn("tester appcast's", publish)

    def test_tester_release_is_a_prerelease(self):
        tag = jobs()['tag']
        self.assertIn('--notes "$notes" --prerelease --latest=false', tag)

    def test_no_human_approval_file(self):
        # Miguel, 21 Nov 2026: no human approval step for releases; the train promotes.
        self.assertFalse((ROOT / 'next/mac/release/public.json').exists())
        self.assertNotIn('public.json', (ROOT / '.github/CODEOWNERS').read_text())

    def test_train_picks_the_newest_tester_build_72h_old(self):
        spec = importlib.util.spec_from_file_location('pick', ROOT / 'next/mac/tools/release-train-pick.py')
        pick = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pick)
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)

        def rel(version, build, age, pre=True, draft=False, tag=None):
            return dict(tag_name=tag or f'v{version}', name=f'WizardOS {version} for Mac (build {build})', prerelease=pre,
                        draft=draft, published_at=None if age is None else (now - timedelta(hours=age)).isoformat())
        rels = [rel('0.8.14', 325, 300, pre=False), rel('0.8.15', 326, 100), rel('0.8.16', 327, 80), rel('0.8.17', 328, 5),
                rel('0.8.18', 329, None, draft=True), rel('0.8.19', 330, 500, tag='v9.9.9'),
                dict(tag_name='try-wizard-0.2.4', name='Try Wizard 0.2.4', prerelease=True, published_at='2026-01-01T00:00:00Z')]
        self.assertEqual(pick.pick(rels, 325, now)[0], ('0.8.16', 327))
        found, why = pick.pick(rels, 327, now)
        self.assertIsNone(found)
        self.assertTrue(why.startswith('WAITING: build 328 (0.8.17) is 5.0h old'), why)
        found, why = pick.pick(rels, 328, now)
        self.assertIsNone(found)
        self.assertTrue(why.startswith('nothing to promote'), why)
        self.assertEqual(pick.pick([rel('0.8.15', 326, 72)], 325, now)[0], ('0.8.15', 326))
        self.assertEqual(pick.SOAK_HOURS, 72)
        now = datetime.now(timezone.utc)
        rels = [rel('0.8.14', 325, 300, pre=False), rel('0.8.15', 326, 100), rel('0.8.16', 327, 80), rel('0.8.17', 328, 5)]
        with tempfile.TemporaryDirectory(prefix='try-wizard-720-') as tmp:
            Path(tmp, 'r.json').write_text(json.dumps([rels[:3], rels[3:]]))
            done = subprocess.run(['python3', str(ROOT / 'next/mac/tools/release-train-pick.py'), str(Path(tmp, 'r.json')), '325'],
                                  capture_output=True, text=True, check=True)
            self.assertEqual(done.stdout, '0.8.16 327\n')

    def test_promote_workflow(self):
        text = PROMOTE.read_text()
        self.assertIn("    - cron: '47 */6 * * *'\n", text)
        self.assertNotIn('push:', text)
        self.assertIn('release-train-pick.py', text)
        self.assertIn('label:release-blocker state:open', text)
        self.assertIn('group: mac-release-main', text, 'never races a tester publish')
        self.assertNotIn('self-hosted', text)
        for use in re.findall(r'uses:\s*(.+)', text):
            self.assertRegex(use.strip(), PIN)
        js = promote_jobs()
        self.assertEqual(list(js), ['read', 'promote', 'release'])
        self.assertIn("if: github.ref == 'refs/heads/main'", js['read'])
        self.assertNotIn('WOS_RELEASE_LANES', text)
        self.assertNotIn('secrets.', js['read'])
        self.assertNotIn('environment:', js['read'])
        # The blocker check sits between the pick and the outputs that start the promotion.
        self.assertLess(js['read'].index('release-blocker'), js['read'].index('>> "$GITHUB_OUTPUT"'))
        promote = js['promote']
        self.assertIn("if: needs.read.outputs.build != ''", promote)
        self.assertIn('environment: mac-publish', promote)
        self.assertEqual(set(re.findall(r'secrets\.(\w+)', promote)),
                         {'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_SESSION_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'})
        self.assertNotIn('actions/checkout', promote)
        self.assertNotIn('uses:', promote)
        self.assertNotIn('next/', promote)
        self.assertNotIn('sign_update', promote, 'promotion never signs: same bytes')
        # Every check before the first write, the feed last.
        for check in ('not higher than the public appcast', 'archive signature does not match', 'feed signature does not match',
                      'names another build', 'Wizard-$VERSION.dmg is not published'):
            self.assertIn(check, promote)
            self.assertLess(promote.index(check), promote.index('put mac/index.html'))
        self.assertLess(promote.index('put mac/index.html'), promote.index('put mac/appcast.xml'))
        self.assertEqual(re.findall(r'(?m)^\s+put (\S+) ', promote), ['mac/index.html', 'mac/appcast.xml'])
        self.assertNotIn('secrets.', js['release'])
        self.assertIn('--prerelease=false --latest', js['release'])


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

    def test_critical_release_marks_the_feed_and_no_field_changes_nothing(self):
        # try-wizard#128: "critical": true in version.json -> <sparkle:criticalUpdate/>; without it, the same bytes.
        stage = stage_module()
        manifest = {'build': '326', 'arch': 'arm64', 'hostProtocol': 1, 'files': {}, 'guestPatch': None}
        args = ('0.8.15', 326, manifest, 'https://downloads.example/mac/326/Wizard-326.zip', 1234)
        plain = stage.appcast_template(*args)
        self.assertEqual(plain, stage.appcast_template(*args, critical=False))
        self.assertNotIn('criticalUpdate', plain)
        # Today's feed (before #128), byte for byte.
        self.assertEqual(plain, (
            '<?xml version="1.0" encoding="utf-8"?>\n<rss xmlns:sparkle="%s" xmlns:wizard="%s" version="2.0"><channel>'
            '<title>WizardOS updates</title><item><title>WizardOS 0.8.15</title><sparkle:version>326</sparkle:version>'
            '<sparkle:shortVersionString>0.8.15</sparkle:shortVersionString>'
            '<sparkle:minimumSystemVersion>14.0.0</sparkle:minimumSystemVersion>'
            '<sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements><wizard:contract>%s</wizard:contract>'
            '<enclosure url="https://downloads.example/mac/326/Wizard-326.zip" type="application/octet-stream" '
            'length="1234" sparkle:edSignature="@ED_SIGNATURE@" /></item></channel></rss>\n'
        ) % (stage.SPARKLE_NS, stage.WIZARD_NS, json.dumps(manifest, sort_keys=True, separators=(',', ':'))))
        urgent = stage.appcast_template(*args, critical=True)
        self.assertEqual(urgent.count(stage.PLACEHOLDER), 1)
        item = X.fromstring(urgent.split('\n', 1)[1]).find('channel/item')
        found = item.find('s:criticalUpdate', {'s': stage.SPARKLE_NS})
        self.assertIsNotNone(found)
        self.assertEqual(len(found), 0)
        self.assertIsNone(found.get('{%s}version' % stage.SPARKLE_NS))   # critical for every older install
        self.assertEqual(urgent.replace('<sparkle:criticalUpdate />', ''), plain)

    def test_manual_below_and_critical_together(self):
        # try-wizard#126 and #128 in one release: both marks, each removable without touching the other.
        stage = stage_module()
        manifest = {'build': '330', 'arch': 'arm64', 'hostProtocol': 1, 'files': {}, 'guestPatch': None}
        args = ('0.9.0', 330, manifest, 'https://downloads.example/mac/330/Wizard-330.zip', 1234)
        both = stage.appcast_template(*args, manual_below=328, critical=True)
        item = X.fromstring(both.split('\n', 1)[1]).find('channel/item')
        ns = {'s': stage.SPARKLE_NS}
        self.assertIsNotNone(item.find('s:criticalUpdate', ns))
        self.assertEqual(item.find('s:informationalUpdate/s:belowVersion', ns).text, '328')
        self.assertEqual(both.replace('<sparkle:criticalUpdate />', ''), stage.appcast_template(*args, manual_below=328))

    def test_critical_is_read_from_version_json(self):
        stage = stage_module()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'version.json'
            f.write_text('{"version": "0.8.15", "build": 326}')
            self.assertFalse(stage.critical(f))
            f.write_text('{"version": "0.8.15", "build": 326, "critical": true}')
            self.assertTrue(stage.critical(f))
            f.write_text('{"version": "0.8.15", "build": 326, "critical": "yes"}')
            with self.assertRaises(AssertionError):
                stage.critical(f)
        self.assertFalse(stage.critical(ROOT / 'next/mac/release/version.json'))

    def test_landing_page_names_the_new_dmg(self):
        page = stage_module().landing_page('0.8.0', 310, 'https://downloads.example/mac/310/Wizard-0.8.0.dmg',
                                           25_000_000, 'ab' * 32)
        self.assertIn('href="https://downloads.example/mac/310/Wizard-0.8.0.dmg"', page)
        self.assertIn('WizardOS 0.8.0', page)
        self.assertIn('build 310', page)
        self.assertIn('ab' * 32, page)


if __name__ == '__main__':
    unittest.main()
