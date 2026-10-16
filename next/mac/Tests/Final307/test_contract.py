#!/usr/bin/env python3
"""Fast control-plane contract checks; no Mac job invocation."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

P = Path(__file__).with_name('run.py')
spec = importlib.util.spec_from_file_location('final307', P)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class Contracts(unittest.TestCase):
    def test_production_pinned(self):
        self.assertEqual(m.PRODUCTION,'c7952d68e6a61da74b1e26485293cb7b5d881c7b')
    def test_function_exact_extraction(self):
        text = 'outside\nstatic func send(_ command: String) {\n if true { call() }\n}\nafter'
        self.assertEqual(m.function(text,'static func send('), text.split('outside\n')[1].split('\nafter')[0])
    def test_missing_function_refuses(self):
        with self.assertRaises(ValueError): m.function('no symbol','missing')
    def test_sha_stream(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file';p.write_bytes(b'contract')
            self.assertEqual(m.sha(p),hashlib.sha256(b'contract').hexdigest())
    def test_preflight_collision_rejects(self):
        xml=b'<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel><item><sparkle:version>307</sparkle:version></item></channel></rss>'
        class Result: stdout=xml
        with patch.object(m,'run',return_value=Result()):
            with self.assertRaises(AssertionError): m.public_inventory()
    def test_public_number_free_requires_both_404s(self):
        xml=b'<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel><item><sparkle:version>306</sparkle:version></item></channel></rss>'
        class Result:
            def __init__(self,out):self.stdout=out
        with patch.object(m,'run',side_effect=[Result(xml),Result(b'404'),Result(b'404')]):
            self.assertEqual(m.public_inventory()['builds'],[306])
        with patch.object(m,'run',side_effect=[Result(xml),Result(b'403')]):
            with self.assertRaises(AssertionError):m.public_inventory()
    def test_no_build_or_publish_execution(self):
        text=P.read_text()
        self.assertNotIn("'bash',mac/'build.sh'",text)
        self.assertNotIn('aiwizards_downloads_publish.py',text)
        self.assertNotIn('wizard_heavy_submit',text)
        self.assertNotIn('caffeinate',text)
        self.assertNotIn('TCC.db',text)
    def test_no_real_vm_fixture(self):
        text=P.read_text(); fixture=P.with_name('fixture.swift').read_text()
        self.assertIn('NOT_A_VM_FINAL307_CONSENT_ONLY',text)
        self.assertIn('Never migrate in UI policy fixture',fixture)
        self.assertIn('No Host launch in policy fixture',fixture)
        self.assertIn("r['readyForPublication']=False",text)
    def test_notification_uses_gui_bootstrap(self):
        import os
        with patch.object(m, 'run') as call, patch.object(m,'NATIVE_NOTIFIER','/tested/native-notifier'):
            m.notify('update-state')
        argv = call.call_args.args[0]
        self.assertEqual(argv[:5], ['sudo','-n','launchctl','asuser',str(os.getuid())])
        self.assertEqual(argv[-2:], ['/tested/native-notifier','update-state'])
        self.assertNotIn('osascript',argv)
    def test_native_notifier_hash_mismatch_refuses(self):
        with patch.object(m,'sha',return_value='actual'):
            with self.assertRaises(AssertionError): m.configure_notifier('/fixture','different')
    def test_host_sender_drains_runloop(self):
        self.assertIn('ProductionHostIPC.send(CommandLine.arguments[3]); RunLoop.current.run(until:',P.read_text())
    def test_package_reuse_pins_report_and_bytes(self):
        text=P.read_text()
        self.assertIn("assert sha(previous_path) == s['reusePackageReportSHA256']", text)
        self.assertIn("assert previous['productionSource'] == PRODUCTION", text)
        self.assertIn("assert sha(stage/name) == expected['sha256']", text)
        self.assertIn("assert previous['cleanupVerified'] and not previous['published']", text)
    def test_probe_accepts_durable_inherited_lease(self):
        text=P.with_name('probe_notifications.py').read_text()
        self.assertIn("s.get('workerLease') == 'inherited'",text)
        self.assertIn("assert not m.mvp_processes()",text)
        self.assertIn("r['cleanupVerified']=props()==before",text)
    def test_no_vm_initialization_preserves_existing_logs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'logs').mkdir(); (root/'logs/host.log').write_bytes(b'prior log')
            m.prepare_no_vm(root);m.prepare_no_vm(root)
            self.assertTrue((root/'os').is_dir())
            self.assertTrue((root/'Files').is_dir())
            self.assertEqual((root/'logs/host.log').read_bytes(),b'prior log')
            self.assertFalse((root/'os/disk.img').exists())
    def test_no_vm_rejects_disk_firmware_and_symlinks(self):
        for name in ('disk.img','boot','firmware','efi-variable-store','manifest.json'):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);(root/'os').mkdir();(root/'os'/name).write_bytes(b'forbidden')
                with self.assertRaises(AssertionError):m.prepare_no_vm(root)
                self.assertEqual((root/'os'/name).read_bytes(),b'forbidden')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'os').mkdir();(root/'os/disk.img').symlink_to(root/'absent')
            with self.assertRaises(AssertionError):m.prepare_no_vm(root)
    def test_continuation_preserves_prior_failure_and_is_separate(self):
        text=P.read_text()
        self.assertIn("assert sha(s['priorTransaction'])==s['priorTransactionSHA256']",text)
        self.assertIn("app=Path(s['repeatApp']); data=root/'relaunch-data'",text)
        self.assertLess(text.index("gate('exact307-native-entry',native)"),text.index("gate('exact307-packaged-self-update',conditional_sparkle)"))
        self.assertIn("assert r['gates']['exact307-launchservices-file-access']['passed'], 'No new app-attributed external IO witness",text)
    def test_prompt_match_exact_owned_app_only(self):
        spec=importlib.util.spec_from_file_location('ownedprompt',P.with_name('owned_removable_prompt.py'))
        assert spec is not None and spec.loader is not None
        pm=importlib.util.module_from_spec(spec);spec.loader.exec_module(pm)
        rows=[{'AXRole':'AXStaticText','AXValue':'“Wizard Native307 Sender.app” would like to access files on a removable volume.'},
              {'AXRole':'AXButton','AXTitle':'Allow'}]
        self.assertTrue(pm.eligible(rows,'Wizard Native307 Sender.app'))
        self.assertFalse(pm.eligible(rows,'Wizard Native307 Other.app'))
        self.assertFalse(pm.eligible(rows+rows,'Wizard Native307 Sender.app'))
        for phrase in ('would like full disk access','would like to access the microphone','would like to control System Events'):
            self.assertFalse(pm.eligible([dict(rows[0],AXValue='“Wizard Native307 Sender.app” '+phrase),rows[1]],'Wizard Native307 Sender.app'))
    def test_prompt_route_is_fail_closed_and_bounded(self):
        text=P.read_text(); helper=P.with_name('owned_removable_prompt.py').read_text()
        self.assertIn('probes<4',text)
        self.assertIn('if len(pids)==1 and exact307:',text)
        self.assertIn("acted=True;target.write_text",text)
        self.assertIn("command(requester)==str(exe)",helper)
        self.assertIn("if allow and len(candidates)==1:",helper)
        self.assertIn("text(window,'AXRole') not in ('AXWindow','AXSheet','AXDialog')",helper)
        self.assertNotIn('System Events',helper)
    def test_source_unchanged_contract(self):
        root=P.parents[4]
        source=(root/'next/mac/App/WizardUpdater.swift').read_text()
        self.assertIn('func admitLegacyBootstrap() -> Bool',source)
        self.assertIn('Activity changed while confirming; upgrade deferred',source)
        self.assertIn('Unknown legacy boot files',source)
        self.assertIn('Not now',source)

if __name__ == '__main__':unittest.main()
