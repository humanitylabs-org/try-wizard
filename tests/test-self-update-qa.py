#!/usr/bin/env python3
"""Portable focused regressions for the native updater QA harness (no AppKit)."""
import ast
import os
import json
import plistlib
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'next/mac/tools/self-update-launch-qa.py'


def harness_functions():
    # Import functions without admitting native QA or touching the user's defaults.
    tree = ast.parse(SOURCE.read_text())
    safe: list[ast.stmt] = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
    namespace = {}
    exec(compile(ast.Module(body=safe, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


class AdmissionTests(unittest.TestCase):
    def test_source_identity_records_actual_clean_head_and_refuses_dirty_or_mismatch(self):
        with tempfile.TemporaryDirectory(prefix='self-update-source.') as tmp:
            repo = Path(tmp)
            subprocess.run(['git','init','-q',str(repo)],check=True)
            subprocess.run(['git','-C',tmp,'config','core.hooksPath','/dev/null'],check=True)
            (repo/'source.txt').write_text('pinned source\n')
            subprocess.run(['git','-C',tmp,'add','.'],check=True)
            subprocess.run(['git','-C',tmp,'-c','user.name=QA','-c','user.email=qa@example.invalid',
                            'commit','-qm','fixture'],check=True)
            head = subprocess.check_output(['git','-C',tmp,'rev-parse','HEAD'],text=True).strip()
            identify = harness_functions()['source_identity']
            self.assertEqual(identify(repo,head),{'head':head,'statusPorcelain':''})
            with self.assertRaisesRegex(AssertionError,'head mismatch'):
                identify(repo,'0'*40)
            (repo/'source.txt').write_text('dirty\n')
            with self.assertRaisesRegex(AssertionError,'clean source tree'):
                identify(repo,head)
            subprocess.run(['git','-C',tmp,'checkout','--','source.txt'],check=True)
            (repo/'untracked.txt').write_text('untracked\n')
            with self.assertRaisesRegex(AssertionError,'untracked.txt'):
                identify(repo,head)

    def test_copied_progress_helper_requires_exact_host_bundle_argument(self):
        ns = harness_functions()
        bundle = Path('/qa space/Wizard.app')
        text = '\n'.join([
            '101 /cache/Launcher/abc/Updater.app/Contents/MacOS/Updater /qa space/Wizard.app 0',
            '102 /cache/Launcher/abc/Updater.app/Contents/MacOS/Updater /qa space/WizardXapp 0',
            '103 /other/Autoupdate org.humanitylabs.wizard.mvp /Users/owner owner',
            '104 /qa space/Wizard.app/Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate org.humanitylabs.wizard.mvp /Users/owner owner',
            '105 /qa space/Wizard.app/Contentsfake/MacOS/Wizard',
        ])
        self.assertEqual(ns['helper_pid_rows'](text,bundle,'org.humanitylabs.wizard.mvp'),[101,104])


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_feed_refuses_either_qa_stamp_before_archiving(self):
        tool = SOURCE.with_name('make-update-feed.py')
        for manifest_qa, plist_qa in [(True, False), (False, True)]:
            with self.subTest(manifest_qa=manifest_qa, plist_qa=plist_qa), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); contents=root/'Wizard.app/Contents'
                (contents/'Resources').mkdir(parents=True)
                (contents/'Info.plist').write_bytes(plistlib.dumps({'WizardUpdateQA':plist_qa}))
                (contents/'Resources/wizard-release.json').write_text(json.dumps({'qa':manifest_qa}))
                result=subprocess.run([sys.executable,str(tool),str(contents.parent),str(root/'feed'),
                    '--base-url','https://example.invalid','--sign-tool','/missing/signer','--key-file','/missing/key'],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('Refusing QA build',result.stderr)
                self.assertFalse(list((root/'feed').glob('*.zip')))

    def test_build_requires_signed_feed_without_expiring_failures(self):
        # Execute the actual build metadata block with tiny Mach-O fixtures.
        build=SOURCE.parents[1]/'build.sh'
        code=build.read_text().split("/usr/bin/python3 - <<'PY'\n",1)[1].split('\nPY',1)[0]
        import struct
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp)/'Wizard.app'; (app/'Contents/Resources').mkdir(parents=True)
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({}))
            header=struct.pack('<8I',0xfeedfacf,0,0,0,1,152,0,0)
            segment=bytearray(152); struct.pack_into('<II',segment,0,0x19,152); struct.pack_into('<I',segment,64,1)
            segment[72:78]=b'__text'; struct.pack_into('<Q',segment,112,1); struct.pack_into('<I',segment,120,184)
            for path in ['Contents/MacOS/Wizard','Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host']:
                target=app/path; target.parent.mkdir(parents=True); target.write_bytes(header+segment+b'x')
            env=os.environ|{'APP':str(app),'SPARKLE_PUBLIC_KEY':'fixture','SPARKLE_FEED':'https://example.invalid/appcast.xml','RELEASE_ID':'fixture','BUILD':'1','WIZARD_UPDATE_QA':'1','GUEST_UPDATE_PAYLOAD':''}
            subprocess.run([sys.executable,'-c',code],env=env,check=True)
            info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
            self.assertEqual(info.get('SUSignedFeedFailureExpirationInterval'),0)
            self.assertTrue(info['WizardUpdateQA'])
            self.assertTrue(json.loads((app/'Contents/Resources/wizard-release.json').read_text())['qa'])


class CleanupTests(unittest.TestCase):
    def test_failed_notification_and_ignored_term_escalate_to_kill(self):
        child = subprocess.Popen([sys.executable, '-c',
            'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(60)'],
            stdout=subprocess.PIPE, text=True)
        assert child.stdout is not None
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            ns = harness_functions()
            ns['live'] = ns['owned_processes'] = lambda: [child.pid] if child.poll() is None else []
            def fail_notify(command):
                raise RuntimeError('notification helper failed')
            ns['notify'] = fail_notify
            result = ns['cleanup_app'](grace=.15)
            self.assertEqual(child.wait(timeout=2), -signal.SIGKILL)
            self.assertEqual([s['signal'] for s in result['signals']], ['SIGTERM', 'SIGKILL'])
            self.assertEqual(result['notifyError'], 'notification helper failed')
            self.assertIsNone(unrelated.poll())
        finally:
            for proc in (child, unrelated):
                if proc.poll() is None: proc.kill()
                proc.wait(timeout=2)
            child.stdout.close()

    def test_graceful_quit_does_not_send_signals(self):
        ns = harness_functions()
        running = [123]
        ns['live'] = ns['owned_processes'] = lambda: running[:]
        ns['notify'] = lambda command: running.clear()
        self.assertEqual(ns['cleanup_app'](grace=.01), {'notifyError': None, 'signals': []})

    def test_owned_executable_and_helper_paths_are_literal_and_anchored(self):
        with tempfile.TemporaryDirectory(prefix='update-qa-(literal).') as tmp:
            app = Path(tmp)/'Wizard.app'
            wizard = app/'Contents/MacOS/Wizard'
            helper = app/'Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate'
            other = Path(tmp)/'WizardXapp/Contents/MacOS/Wizard'
            children = []
            try:
                for executable in (wizard, helper, other):
                    executable.parent.mkdir(parents=True)
                    executable.symlink_to('/bin/sleep')
                    children.append(subprocess.Popen([str(executable), '60']))
                ns = harness_functions(); ns['installed'] = app
                self.assertEqual(ns['live'](), [children[0].pid])
                self.assertEqual(set(ns['owned_processes']()), {p.pid for p in children[:2]})
            finally:
                for proc in children:
                    proc.kill(); proc.wait(timeout=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
