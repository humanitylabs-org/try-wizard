#!/usr/bin/env python3
"""next/mac/tools/upgrade-test.py (try-wizard#129): the parts that decide what the release upgrade test runs.
The Mac part (real Sparkle installs) runs in the release workflow's upgrade-test job on macos-15."""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOL = ROOT / 'next/mac/tools/upgrade-test.py'
spec = importlib.util.spec_from_file_location('upgrade_test', TOOL)
U = importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)

LIVE = """<?xml version="1.0" encoding="utf-8" standalone="yes"?><!-- sparkle-sign-warning:
IMPORTANT: signed -->
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0"><channel><title>WizardOS updates</title>
<item><title>WizardOS 0.8.14</title><sparkle:version>325</sparkle:version>
<enclosure url="https://downloads.aiwizards.com/mac/325/Wizard-325.zip" type="application/octet-stream" length="4120356" sparkle:edSignature="x"></enclosure></item>
</channel></rss><!-- sparkle-signatures:
edSignature: abc
length: 6856
-->
"""


class UpgradeTestPlan(unittest.TestCase):
    def test_reads_the_live_build_and_its_archive(self):
        self.assertEqual(U.newest(LIVE), (325, 'https://downloads.aiwizards.com/mac/325/Wizard-325.zip', 4120356))

    def test_newest_of_several_items(self):
        two = LIVE.replace('</channel>', '<item><sparkle:version>330</sparkle:version><enclosure url="u330" length="5"/></item></channel>')
        self.assertEqual(U.newest(two)[0], 330)

    def test_a_feed_without_builds_is_an_error(self):
        with self.assertRaises(ValueError):
            U.newest('<rss><channel></channel></rss>')

    def test_live_step_runs_for_a_newer_candidate(self):
        self.assertEqual(U.plan_live_step(325, 326), (True, ''))

    def test_live_step_skipped_before_the_qa_channel(self):
        go, why = U.plan_live_step(U.FIRST_QA_BUILD - 1, 400)
        self.assertFalse(go)
        self.assertIn('QA control channel', why)

    def test_live_step_skipped_when_the_candidate_is_not_newer(self):
        go, why = U.plan_live_step(325, 325)
        self.assertFalse(go)
        self.assertIn('not older', why)

    def test_loopback_feed_moves_only_the_enclosure(self):
        template = ('<rss><channel><item><wizard:contract>{"build":"326"}</wizard:contract>'
                    '<enclosure url="https://downloads.aiwizards.com/mac-dryrun/326/Wizard-326.zip" length="9" '
                    'sparkle:edSignature="@ED_SIGNATURE@"/></item></channel></rss>')
        text = U.loopback_feed(template, 'https://downloads.aiwizards.com/mac-dryrun', 'http://127.0.0.1:48219')
        self.assertIn('url="http://127.0.0.1:48219/326/Wizard-326.zip"', text)
        self.assertEqual(text.count('@ED_SIGNATURE@'), 1)
        self.assertEqual(text.replace('http://127.0.0.1:48219/', 'https://downloads.aiwizards.com/mac-dryrun/'), template)
        with self.assertRaises(ValueError):
            U.loopback_feed(template, 'https://downloads.aiwizards.com/mac', 'http://127.0.0.1:48219')

    def test_loopback_feed_command(self):
        with tempfile.TemporaryDirectory(prefix='try-wizard-129-') as tmp:
            src = pathlib.Path(tmp, 'appcast.template.xml')
            src.write_text('<enclosure url="https://d.example/mac/1/Wizard-1.zip"/>')
            out = pathlib.Path(tmp, 'up/appcast-candidate.template.xml')
            subprocess.run([sys.executable, TOOL, 'loopback-feed', '--template', src, '--out', out,
                            '--public-base', 'https://d.example/mac', '--loopback-base', 'http://127.0.0.1:48219'],
                           check=True)
            self.assertEqual(out.read_text(), '<enclosure url="http://127.0.0.1:48219/1/Wizard-1.zip"/>')

    def test_summary_names_every_step(self):
        text = U.summary([{'step': 'live 325 -> candidate 326', 'result': 'pass', 'detail': 'ok'},
                          {'step': 'candidate 326 -> candidate + 1 (327)', 'result': 'fail', 'detail': 'a|b'},
                          {'step': 's', 'result': 'skip', 'detail': 'why'}])
        self.assertIn('| live 325 -> candidate 326 | passed | ok |', text)
        self.assertIn('| FAILED | a/b |', text)
        self.assertIn('| skipped | why |', text)

    def test_stand_in_page_is_trusted_and_idle(self):
        # main.swift resolveHome wants data-shell on /wizard-os-home/desktop.html; admitUpdateRestart reads __wux.voice.
        self.assertIn('data-shell', U.STUB_PAGE)
        self.assertIn('window.__wux = {voice: "idle"}', U.STUB_PAGE)
        main = (ROOT / 'next/mac/App/main.swift').read_text()
        self.assertIn('const state = window.__wux?.voice ?? window.__wos?.voice;', main)
        self.assertIn('contains("data-shell")', main)

    def test_qa_channel_commands_exist_in_the_app(self):
        main = (ROOT / 'next/mac/App/main.swift').read_text()
        for command in ('update-check', 'update-restart', 'update-state', 'update-quit'):
            self.assertIn('case "%s"' % command, main)
        tool = TOOL.read_text()
        for key in ('DataHome', 'QAHooks', 'SUEnableAutomaticChecks', 'SUFeedURL', 'backends'):
            self.assertIn("'%s'" % key, tool)
        updater = (ROOT / 'next/mac/App/WizardUpdater.swift').read_text()
        self.assertIn('journal["phase"] = "native-activated"', updater)


if __name__ == '__main__':
    unittest.main()
