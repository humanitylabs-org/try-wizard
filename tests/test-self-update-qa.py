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
from unittest.mock import Mock
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


class NegativeFeedTests(unittest.TestCase):
    """Protocol fixtures exercise the real harness functions, not native Sparkle."""
    def launch_fixture(self):
        ns=harness_functions()
        ns.update(installed=Path('/fixture/Wizard.app'), data=Path('/fixture/data'),
                  base='http://127.0.0.1:1234', requests=[], version=lambda:'18002')
        state={'build':'18002','phase':'idle','ready':False}
        def open_app(command):
            if '-SUEnableAutomaticChecks' not in command:
                ns['requests'].append('/appcast.xml')
                state.update(phase='ready',ready=True)
        ns['run']=Mock(side_effect=open_app)
        ns['notify']=Mock()
        ns['wait_state']=lambda check: self.assertTrue(check(state))
        ns['snapshot']=lambda:state.copy()
        ns['time']=Mock()
        return ns,state

    def test_manual_launch_prevents_r6_cached_ready_without_changing_default_launch(self):
        ns,state=self.launch_fixture()
        ns['launch'](automatic_checks=False)
        self.assertEqual(ns['run'].call_args.args[0][-2:],['-SUEnableAutomaticChecks','NO'])
        self.assertEqual(ns['requests'],[])
        self.assertEqual(state['phase'],'idle')
        ns['launch']()
        self.assertNotIn('-SUEnableAutomaticChecks',ns['run'].call_args.args[0])
        self.assertEqual(state['phase'],'ready')

    def test_manual_launch_refuses_unexpected_ready_or_early_feed_fetch(self):
        for ready in (False,True):
            with self.subTest(ready=ready):
                ns,state=self.launch_fixture()
                def premature_check(command):
                    ns['requests'].append('/appcast.xml')
                    if ready: state.update(phase='ready',ready=True)
                ns['run'].side_effect=premature_check
                with self.assertRaises(AssertionError): ns['launch'](automatic_checks=False)

    def case_fixture(self, root, **changes):
        ns=harness_functions()
        path=Path(root)/'appcast.xml'; path.write_bytes(b'edited signed feed fixture')
        digest=ns['hashlib'].sha256(path.read_bytes()).hexdigest()
        initial={'phase':'idle','ready':False,'phaseHistory':[]}
        final={'phase':'failed','message':'improperly signed','ready':False,'freshDownloadReady':False,
               'phaseHistory':['checking','failed'],
               'errors':[{'domain':'SUSparkleErrorDomain','code':1000},
                         {'domain':'SUSparkleErrorDomain','code':3002}]}
        final.update(changes)
        ns.update(feed=Path(root),requests=[],feed_requests=[],snapshot=lambda:initial.copy(),
                  version=lambda:'18002')
        def check(command):
            self.assertEqual(command,'update-check')
            ns['requests'].append('/appcast.xml')
            ns['feed_requests'].append({'sha256':digest,'bytes':path.stat().st_size})
        ns['notify']=Mock(side_effect=check)
        def wait(predicate, seconds):
            self.assertTrue(predicate(final),'Negative oracle did not accept fresh failure')
            return final
        ns['wait_state']=wait
        ns['record']=Mock()
        ns['time']=Mock()
        ns['time'].time.side_effect=[0,0,91]
        return ns,initial,final,digest

    def test_signed_feed_failure_requires_exact_fetched_bytes_and_error_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns,_,final,digest=self.case_fixture(tmp)
            ns['fail_without_replacement']('edited-feed','improperly signed',archive=False,signature=True,outer_code=1000)
            ns['record'].assert_called_once_with('edited-feed',final)
            self.assertEqual(final['requestEvidence']['feedSHA256'],digest)
            self.assertEqual(final['requestEvidence']['paths'],['/appcast.xml'])

    def test_negative_case_refuses_cached_ready_before_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns,initial,_,_=self.case_fixture(tmp)
            initial.update(phase='ready',ready=True)
            with self.assertRaisesRegex(AssertionError,'cached Ready'):
                ns['fail_without_replacement']('edited-feed','improperly signed',archive=False)
            ns['notify'].assert_not_called()
            ns['record'].assert_not_called()

    def test_missing_or_wrong_feed_cannot_pass_even_with_signature_error(self):
        for paths,receipt in [([],None),(['/appcast.xml'],None),(['/appcast.xml'],'wrong-digest')]:
            with self.subTest(paths=paths,receipt=receipt), tempfile.TemporaryDirectory() as tmp:
                ns,_,_,_=self.case_fixture(tmp)
                def check(command):
                    ns['requests'].extend(paths)
                    if receipt: ns['feed_requests'].append({'sha256':receipt})
                ns['notify'].side_effect=check
                with self.assertRaisesRegex(AssertionError,'never reached its exact feed/archive'):
                    ns['fail_without_replacement']('edited-feed','improperly signed',archive=False,signature=True,outer_code=1000)
                ns['record'].assert_not_called()

    def test_wrong_error_stale_failure_or_ready_cannot_pass(self):
        changes=[{'errors':[]}, {'errors':[{'domain':'SUSparkleErrorDomain','code':4005},
                                         {'domain':'SUSparkleErrorDomain','code':3002}]},
                 {'message':'unrelated failure'}, {'phaseHistory':[]},
                 {'ready':True}, {'freshDownloadReady':True}]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                ns,_,_,_=self.case_fixture(tmp,**change)
                with self.assertRaises(AssertionError):
                    ns['fail_without_replacement']('edited-feed','improperly signed',archive=False,signature=True,outer_code=1000)
                ns['record'].assert_not_called()

    def test_feed_rejection_cannot_download_archive_or_replace_installed_build(self):
        for replacement in (False,True):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as tmp:
                ns,_,_,_=self.case_fixture(tmp)
                if replacement: ns['version']=Mock(side_effect=['18002','18003'])
                else:
                    check=ns['notify'].side_effect
                    def with_archive(command):
                        check(command); ns['requests'].append('/Wizard-18003.zip')
                    ns['notify'].side_effect=with_archive
                with self.assertRaises(AssertionError):
                    ns['fail_without_replacement']('edited-feed','improperly signed',archive=False,signature=True,outer_code=1000)
                ns['record'].assert_not_called()

    def test_http_receipt_hashes_the_exact_edited_feed_bytes_served(self):
        # Exercise the actual native harness's Handler with real loopback HTTP;
        # app/Sparkle callbacks remain outside this portable test's claim.
        ns=harness_functions()
        handler=next(n for n in ast.walk(ast.parse(SOURCE.read_text())) if isinstance(n,ast.ClassDef) and n.name=='Handler')
        exec(compile(ast.Module(body=[handler],type_ignores=[]),str(SOURCE),'exec'),ns)
        import urllib.request
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ns.update(feed=root,evidence=root,feed_requests=[],requests=[])
            server=ns['http'].server.ThreadingHTTPServer(('127.0.0.1',0),ns['Handler'])
            thread=ns['threading'].Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                for body in [b'original signed feed',b'edited after signing']:
                    (root/'appcast.xml').write_bytes(body)
                    with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/appcast.xml') as response:
                        self.assertEqual(response.read(),body)
                    self.assertEqual(ns['feed_requests'][-1],{'sha256':ns['hashlib'].sha256(body).hexdigest(),'bytes':len(body)})
                self.assertEqual(ns['requests'],['/appcast.xml','/appcast.xml'])
                self.assertEqual(json.loads((root/'feed-requests.json').read_text()),ns['feed_requests'])
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_native_negative_suite_uses_manual_launch_after_host_stop(self):
        text=SOURCE.read_text()
        boundary=text.index("record('quit-during-stopping-rolls-back-host-before-exit')")
        negative=text.index("fail_without_replacement('feed-edited-after-signing-rejected'",boundary)
        tree=ast.parse(text[boundary:negative].split('\n',1)[1].replace('\n    ','\n').lstrip())
        launches=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='launch']
        self.assertEqual(len(launches),1)
        self.assertEqual([(kw.arg,ast.literal_eval(kw.value)) for kw in launches[0].keywords],[('automatic_checks',False)])


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
