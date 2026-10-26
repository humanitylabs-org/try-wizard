#!/usr/bin/env python3
"""Focused safety contracts for final-release fresh install (no macOS/VM needed)."""
import ast
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'next/mac/tools/fresh-install-release-qa.py'


def helpers():
    tree=ast.parse(SOURCE.read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef))]
    scope={};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
    return scope


class FreshInstallSafetyTests(unittest.TestCase):
    def test_fresh_install_pre_answers_files_folder(self):
        ns=helpers()
        with tempfile.TemporaryDirectory() as root:
            out=Path(root);data=out/'data';data.mkdir();files=out/'files'
            evidence=ns['preanswer_files_folder'](data,files)
            self.assertEqual(json.loads((data/'files-folder.json').read_text()),{'path':str(files)})
            self.assertTrue(files.is_dir())
            self.assertEqual([p.name for p in data.iterdir()],['files-folder.json'])
            self.assertTrue(evidence['filesFolderPromptPreAnswered'])
            self.assertFalse(evidence['finalAppFinderConsentProven'])
            self.assertEqual(evidence['filesFolder'],str(files))
        text=SOURCE.read_text()
        self.assertLess(text.index("setup=preanswer_files_folder(data,out/'files')"),text.index('appproc=subprocess.Popen'))
        self.assertIn("'publication':'none',**setup",text)

    def test_fresh_install_selects_codable_this_mac_backend_not_unanswered_chooser(self):
        ns=helpers();overlay=ns['isolated_overlay']({'keep':'unchanged'},Path('/isolated/data'),'http://127.0.0.1/feed')
        self.assertEqual(overlay['activeBackend'],0)
        self.assertEqual(json.loads(overlay['backends']),[{'name':'This Mac','kind':'thisMac','url':'http://127.0.0.1:48030/'}])
        self.assertFalse(overlay['QAHooks'])
        self.assertEqual(overlay['keep'],'unchanged')
        # Backend's required Codable fields must remain synchronized with the app.
        source=(ROOT/'next/mac/App/main.swift').read_text()
        for field in ('var kind: Kind','var name: String','var url: String','d.integer(forKey: "activeBackend")'):
            self.assertIn(field,source)

    def test_preference_restore_removes_overlay_only_keys(self):
        ns=helpers();ns['DOMAIN']='isolated.test.domain'
        original={'DataHome':'/real','retained':b'bytes','nested':{'keep':True}}
        state=dict(original,ShowMenuBarIcon=False,SUEnableAutomaticChecks=False,
                   SUHasLaunchedBefore=True,WizardKeyEnabled=False,WizardKeyUseGlobal=False)
        actions=[]
        with tempfile.TemporaryDirectory() as root:
            backup=Path(root)/'backup.plist';backup.write_bytes(plistlib.dumps(original))
            def defaults(*argv):
                actions.append(argv)
                self.assertEqual(argv[:1],('/usr/bin/defaults',))
                self.assertEqual(argv[2],ns['DOMAIN'])
                if argv[1]=='delete':state.clear()
                elif argv[1]=='import':state.update(plistlib.loads(Path(argv[3]).read_bytes()))
                else:self.fail(str(argv))
            ns['run']=defaults;ns['preferences']=lambda:dict(state)
            ns['restore_preferences'](original,backup)
            self.assertEqual(state,original)
            self.assertEqual([a[1] for a in actions],['delete','import'])

    def test_preference_restore_removes_domain_when_original_absent(self):
        ns=helpers();ns['DOMAIN']='isolated.test.domain';ns['run']=Mock();ns['preferences']=lambda:None
        ns['restore_preferences'](None,Path('/unused/backup'))
        ns['run'].assert_called_once_with('/usr/bin/defaults','delete',ns['DOMAIN'])

    def test_preference_export_empty_dict_distinguishes_absent_domain(self):
        ns=helpers();ns['DOMAIN']='isolated.test.domain'
        exported=subprocess.CompletedProcess([],0,plistlib.dumps({}),b'')
        absent=subprocess.CompletedProcess([],1,b'',b'Domain does not exist')
        present=subprocess.CompletedProcess([],0,b'{}',b'')
        saved=ns['subprocess'].run
        try:
            ns['subprocess'].run=Mock(side_effect=[exported,absent])
            self.assertIsNone(ns['preferences']())
            ns['subprocess'].run=Mock(side_effect=[exported,present])
            self.assertEqual(ns['preferences'](),{})
        finally:
            ns['subprocess'].run=saved

    def test_missing_first_feed_request_has_short_diagnostic_deadline(self):
        text=SOURCE.read_text()
        self.assertIn("300,'release app first feed request (check backend selection/Files-folder prompt and app.log)'",text)

    def test_cleanup_owns_exact_host_executable_and_exact_data_home_not_prefix(self):
        ns=helpers(); app=Path('/qa space/Wizard.app'); data=Path('/qa space/data')
        host=app/'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host'
        ns['process_rows']=lambda:[(1,str(host)+' --wizard-data-home '+str(data)),
                                  (2,str(host)+' --wizard-data-home '+str(data)+'2'),
                                  (3,str(host)+'2 --wizard-data-home '+str(data)),
                                  (4,str(host)+' --wizard-data-home /real/data')]
        self.assertEqual(ns['owned_hosts'](app,data),[1])

    def test_no_broad_process_kill_no_data_wipe(self):
        text=SOURCE.read_text()
        for bad in ('pkill','killall','shutil.rmtree','rm -rf','os.kill('):
            self.assertNotIn(bad,text.replace('No broad pkill','No broad process kill'))
        self.assertIn('assert not foreign',text)
        self.assertIn('app.executableURL?.resolvingSymlinksInPath()==expected',text)

    def test_final_app_is_unmodified_and_qa_hooks_are_off(self):
        text=SOURCE.read_text()
        self.assertIn("assert not info.get('WizardUpdateQA') and not release.get('qa')",text)
        self.assertIn('QAHooks=False',text)
        self.assertNotIn('qa.sh',text)
        self.assertNotIn('codesign\',\'--force',text)

    def test_restore_is_finally_protected_and_verified_against_original(self):
        text=SOURCE.read_text()
        self.assertIn('finally:',text)
        self.assertIn('assert preferences()==original',text)
        self.assertIn("assert after==before",text)
        self.assertIn('signal.signal(signal.SIGTERM,interrupt)',text)
        self.assertIn('signal.signal(signal.SIGINT,interrupt)',text)

    def test_loopback_p2_feed_requires_real_download_requests_and_part_hashes(self):
        text=SOURCE.read_text()
        for fragment in ("('127.0.0.1',0)","'/os/p2/latest.json'", "digest(src)==part['sha256']",
                         "for part in feed['parts']:assert part['url'] in paths", "manifest=bounded_wait(installed"):
            self.assertIn(fragment,text)

    def test_two_health_endpoints_belong_to_owned_host_and_retained_0_5_0_manifest(self):
        text=SOURCE.read_text()
        for fragment in ("m['version']=='0.5.0'", "status['pid'] in owned_hosts(app,data)",
                         '48030/healthz','48023/wizard/health',"'0.7.2'","'309'"):
            self.assertIn(fragment,text)


if __name__=='__main__':unittest.main(verbosity=2)
