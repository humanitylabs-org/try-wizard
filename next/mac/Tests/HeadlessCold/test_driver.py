#!/usr/bin/env python3
"""Cheap extraction/comparison contracts only; NEVER real-VM acceptance."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import build_driver
import run as runner
SOURCE=HERE.parents[3]

class DriverContracts(unittest.TestCase):
    def test_application_readiness_waits_and_fails_closed(self):
        import io
        from unittest.mock import patch
        import guest_audit
        with patch.object(guest_audit.urllib.request,'urlopen',side_effect=[ConnectionRefusedError(),io.BytesIO(b'{"upstream_reachable":true}')]) as opener, patch.object(guest_audit.time,'sleep'):
            self.assertTrue(guest_audit.wait_health()['upstream_reachable'])
            request = opener.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8924/wizard/health')
            self.assertEqual(request.get_header('Host'), '127.0.0.1:48023')
        with patch.object(guest_audit.urllib.request,'urlopen',side_effect=ConnectionRefusedError()), patch.object(guest_audit.time,'monotonic',side_effect=[0,1]):
            with self.assertRaises(TimeoutError): guest_audit.wait_health(timeout=0)

    def test_host_layout_precedes_vm_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'isolated/data'
            runner.prepare_directories(data)
            self.assertTrue((data/'os').is_dir())
            self.assertTrue((data/'logs').is_dir())
            (data/'logs/console.log').write_text('boot witness')
            runner.prepare_directories(data)
            self.assertEqual((data/'logs/console.log').read_text(),'boot witness')
            self.assertFalse((data/'os/disk.img').exists())

    def test_exact_extraction_and_desktop_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'generated'
            manifest=build_driver.generate(SOURCE,out)
            vm=(out/'VM.swift').read_text()
            self.assertIn('cachingMode: .cached, synchronizationMode: .full',vm)
            self.assertIn('init=/bin/sh wizard.dev=1 wizard.cold=',vm)
            self.assertIn('VZSharedDirectory(url: payload, readOnly: true)',vm)
            self.assertIn('func runGuestPatch',vm)
            self.assertIn('final class ColdBootstrapSerial',vm)
            self.assertIn('self.coldSerial?.generation == generation',vm)
            self.assertIn('try Data().write(to: consoleURL)',vm)
            self.assertIn('private func waitForColdShell',vm)
            joined='\n'.join(p.read_text() for p in out.glob('*.swift'))
            for desktop in ('import AppKit','NSWorkspace.shared','NSApplication.shared','NSApp.','caffeinate','launchctl','osascript'):
                self.assertNotIn(desktop,joined)
            self.assertNotIn('UserDefaults', (out/'Shared.swift').read_text())
            for name in ('WizardGuestActivation.swift','UpdateContract.swift','DiskIdentity.swift','GuestPatchCommand.swift'):
                original = SOURCE/('next/mac/App/' if name=='WizardGuestActivation.swift' else 'next/mac/Shared/')/name
                expected=original.read_text().replace('import AppKit','import Foundation')
                self.assertEqual((out/name).read_text(),expected)
            for name,sha in manifest['generated'].items():
                self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),sha)
            self.assertIn('try WizardGuestActivation.snapshotStoppedDisk()', (out/'Admission.swift').read_text())

    def test_fail_closed_production_drift(self):
        # Resolve a real source mismatch without compiling or exercising any VM.
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch
            with patch.object(build_driver.subprocess,'check_output',return_value=b'not pinned source'):
                with self.assertRaisesRegex(RuntimeError,'Production source drift'):
                    build_driver.generate(SOURCE,Path(tmp)/'generated')

    def test_preservation_comparator_rejects_loss(self):
        spec=importlib.util.spec_from_file_location('preservation',SOURCE/'next/guest/stack-preservation.py')
        assert spec is not None and spec.loader is not None
        guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
        before={'protected':{'file':'hash'},'installedApps':['hermes-agent'],'accountFiles':{},
            'configNormalizedSHA256':'config','configRawSHA256':'old','configExpectedSHA256':'new',
            'authSnapshot':guard.auth_snapshot(None),
            'databases':{'state.db':{'messages':{'columns':['id'],'rows':['message-hash']},
                                     'sessions':{'columns':['id'],'rows':['session-hash']}}}}
        after=copy.deepcopy(before);after['configRawSHA256']='new'
        self.assertTrue(runner.compare(before,after,guard)['existingRowsPreserved'])
        for key in ('protected','installedApps','configRawSHA256'):
            bad=copy.deepcopy(after);bad[key]={} if isinstance(bad[key],dict) else 'wrong'
            with self.assertRaises(AssertionError):runner.compare(before,bad,guard)
        bad=copy.deepcopy(after);bad['databases']['state.db']['messages']['rows']=[]
        with self.assertRaises(AssertionError):runner.compare(before,bad,guard)
        with self.assertRaises(AssertionError):runner.compare(before,after,guard,rollback=True)

    def test_build_wrapper_keeps_exact_sources_and_no_gui_route(self):
        import build_and_run
        source=(HERE/'build_and_run.py').read_text()
        self.assertEqual(build_and_run.PRODUCTION,build_driver.PRODUCTION)
        self.assertIn('clean_pin(source, PRODUCTION)',source)
        self.assertIn("RELEASE_ID=PRODUCTION, SIGN_IDENTITY='-', DMG='0'",source)
        self.assertIn("assert real['success'] and real['cleanupVerified']",source)
        self.assertIn("assert (source/name).read_bytes() == pinned == (harness/name).read_bytes()",source)
        self.assertNotIn("mac/'Tests/legacy061_probe.py'",source)
        self.assertIn("'--worker-lease','inherited'",source)

    def test_real_restart_audit_rejects_missing_fence_or_stock_execution(self):
        from unittest.mock import patch, Mock
        import guest_audit
        for failure in (None, 'same-pid', 'missing-plugin', 'stock-started', 'policy-drift', 'daemon-drift', 'allow-route', 'restart-timeout'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); policy=root/'policy.json'; daemon=root/'daemon.json'; dropin=root/'runtime/dropin'
                cid='a'*64
                policy.write_text(json.dumps({'containers':{cid:{}}})); daemon.write_text('{"authorization-plugins":["wizard-cold"]}')
                before={'coldBoot':True,'bootID':'same','fence':{'phase':'committed','forbiddenExecutionEvents':0,'historyNotSaturated':True}}
                container={'Id':cid,'Image':guest_audit.STOCK,'State':{'StartedAt':'original','Running':False},'HostConfig':{'RestartPolicy':{'Name':'no','MaximumRetryCount':0}}}
                replaced=False
                def run(*args):
                    nonlocal replaced
                    if args[:2]==('systemctl','restart'):
                        if failure=='restart-timeout': raise TimeoutError('daemon never stopped cleanly')
                        replaced=True
                        if failure=='policy-drift': policy.write_text('{}')
                        if failure=='daemon-drift': daemon.write_text('{}')
                        return ''
                    if args[:2]==('systemctl','show'): return '100' if not replaced or failure=='same-pid' else '101'
                    if args[:2]==('systemctl','daemon-reload'): return ''
                    if args[:2]==('docker','ps'): return cid
                    if args[:2]==('docker','info'): return '[]' if failure=='missing-plugin' else '["wizard-cold"]'
                    if args[:2]==('docker','inspect'):
                        c=copy.deepcopy(container)
                        if replaced and failure=='stock-started': c['State']['StartedAt']='new'
                        return json.dumps([c])
                    raise AssertionError(args)
                def path(value):
                    if value=='/etc/docker/daemon.json': return daemon
                    if value=='/run/systemd/system/docker.service.d/headless-clean-restart.conf': return dropin
                    return Path(value)
                with patch.object(guest_audit,'POLICY',policy), patch.object(guest_audit,'Path',side_effect=path), patch.object(guest_audit,'snapshot',return_value=copy.deepcopy(before)), patch.object(guest_audit,'run',side_effect=run), patch.object(guest_audit.subprocess,'run',return_value=Mock(returncode=0 if failure=='allow-route' else 1,stderr='WIZARD_COLD_DENIED')):
                    if failure:
                        with self.assertRaises((AssertionError,TimeoutError)): guest_audit.same_boot_restart()
                    else:
                        report=guest_audit.same_boot_restart()['daemonReplacement']
                        self.assertTrue(report['sameBoot'] and report['forceKillDisabled'])
                        self.assertEqual(set(report['deniedRoutes']),{'create','start','restart','unpause','exec'})
                    self.assertFalse(dropin.exists())

    def test_restart_and_normal_recovery_gates_are_mandatory(self):
        audit=(HERE/'guest_audit.py').read_text(); driver=(HERE/'main.swift').read_text(); run=(HERE/'run.py').read_text()
        self.assertIn('audit("cold-restarted")',driver)
        self.assertIn('WIZARD_HEADLESS_RESTART_AUDIT',driver)
        self.assertIn("for label in ('cold-before','cold-after','cold-restarted')",run)
        self.assertIn("after['normalBootRestoration']['originalDaemonBytesRestored']",run)
        self.assertIn("policy['phase']=='activated'",audit)
        self.assertIn("c['HostConfig']['RestartPolicy']==old['restart']",audit)
        self.assertIn("'productionReleaseID':PRODUCTION",run)
        self.assertIn('"productionReleaseID":"'+build_driver.PRODUCTION+'"',driver)

    def test_failure_cannot_be_reported_as_acceptance(self):
        source=(HERE/'run.py').read_text()
        self.assertIn("assert rc==0 and result['success'] and result['stopped']",source)
        self.assertIn("assert report['success'] and report['cleanupVerified']",source)
        self.assertIn("assert len(events)<256",(HERE/'guest_audit.py').read_text())
        self.assertNotIn('wizard_heavy_submit', source.replace('Durable-worker-only',''))

if __name__=='__main__':unittest.main()
