#!/usr/bin/env python3
"""No-process fixtures for the legacy QA harness identity boundary."""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('legacy061_probe.py'))
assert spec is not None and spec.loader is not None
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)

class ProcessIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = Path(self.tmp.name)/'Wizard with spaces.app'
        self.host = self.app/'Contents/Library/LoginItems/Wizard Host.app'
    def bundle(self, path, identity, executable):
        (path/'Contents').mkdir(parents=True, exist_ok=True)
        (path/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':identity,'CFBundleExecutable':executable,'CFBundleShortVersionString':'0.5.1'}))
        return str(path/'Contents/MacOS'/executable)
    def legacy(self):
        self.bundle(self.app, 'org.humanitylabs.wizard','Wizard')
        return self.bundle(self.host,'org.humanitylabs.wizard.host','Wizard Host')
    def test_mvp_app_and_host_always_refused(self):
        for path, identity, executable in [(self.app,P.DOMAIN,'Wizard'),(self.host,P.DOMAIN+'.host','Wizard Host')]:
            command=self.bundle(path,identity,executable)
            with self.assertRaisesRegex(RuntimeError,'Competing MVP'): P.wizard_process_identity(1,command)
    def test_known_disjoint_host_identity(self):
        result=P.wizard_process_identity(78546,self.legacy())
        self.assertEqual(result['bundleID'],'org.humanitylabs.wizard.host')
        self.assertEqual(result['outerBundleID'],'org.humanitylabs.wizard')
        self.assertEqual(result['preferencesDomain'],'org.humanitylabs.wizard')
        self.assertEqual(Path(result['supportDir']).name,'Wizard')
    def test_missing_unknown_and_mismatched_identity_fail_closed(self):
        command=self.legacy()
        (self.host/'Contents/Info.plist').unlink()
        with self.assertRaises(FileNotFoundError): P.wizard_process_identity(1,command)
        for identity, executable in [('other.product','Wizard Host'),('org.humanitylabs.wizard.host','Other')]:
            self.bundle(self.host,identity,executable)
            with self.assertRaises(RuntimeError): P.wizard_process_identity(1,command)
        with self.assertRaises(RuntimeError): P.wizard_process_identity(1,'not-a-bundle/Contents/MacOS/Wizard')
    def test_disjoint_ports_recorded_and_selected_ports_refused(self):
        command=self.legacy()
        with patch.object(P,'process_rows',return_value=[(78546,command)]), patch.object(P,'run') as run:
            run.return_value=Mock(returncode=0,stdout='p78546\nn127.0.0.1:47823\nn127.0.0.1:47830\n')
            self.assertEqual(P.assert_no_competing_wizard()[0]['listeningPorts'],[47823,47830])
            for port in (48000,48023,48030):
                run.return_value=Mock(returncode=0,stdout='p78546\nn127.0.0.1:'+str(port)+'\n')
                with self.assertRaisesRegex(RuntimeError,'unexpected listening ports'): P.assert_no_competing_wizard()
    def test_missing_outer_identity_is_not_disjoint(self):
        command=self.legacy()
        self.bundle(self.app,P.DOMAIN,'Wizard')
        with self.assertRaisesRegex(RuntimeError,'outer'): P.wizard_process_identity(1,command)

if __name__=='__main__': unittest.main()
