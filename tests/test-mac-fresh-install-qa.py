#!/usr/bin/env python3
"""Focused safety contracts for final-release fresh install (no macOS/VM needed)."""
import ast
from pathlib import Path
import subprocess
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
