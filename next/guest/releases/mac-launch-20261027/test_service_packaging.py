"""Core service remediation contracts; real TLS/start acceptance runs on Thales."""
import contextlib, io, json, os, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch
import local_oci as oci
from test_recorder_packaging import module

package=module('service_core_contract','package-image.py')
HERE=Path(__file__).resolve().parent

class ServicePackagingTests(unittest.TestCase):
    def test_service_final_stage_reuses_pinned_security_remediation(self):
        inputs=package.service_security_inputs()
        with tempfile.TemporaryDirectory() as d:
            context=Path(d)
            helper=types.SimpleNamespace(wheel=lambda target,plan:self.assertEqual(plan,inputs))
            with patch.object(package,'module',return_value=helper),patch.object(package,'service_security_inputs',return_value=inputs):
                text=package.service_remediation(context)
            self.assertEqual((context/'remediate-trust.py').read_bytes(),(HERE/'remediate-trust.py').read_bytes())
            self.assertIn('ca-certificates curl python3 openssl',text)
            self.assertIn('--pip-wheel /opt/wizard-security/pip.whl',text)
            self.assertNotIn('ensurepip/_bundled',text)  # remediate, never delete bootstrap capability
        plan=json.loads((HERE/'security-image-plan.json').read_text())
        for key in ['pip','certifi']:self.assertEqual(inputs['upstreamInputs'][key],plan['upstreamInputs'][key])

    def test_exact_job05_probe_is_read_only_and_failure_is_retained(self):
        closure=module('service_job05_contract','security-closure.py')
        for rc in [0,1]:
            with self.subTest(returncode=rc),tempfile.TemporaryDirectory() as d:
                out=Path(d);row={'ref':'ghcr.io/humanitylabs-org/wizard-agent-service','digest':'sha256:'+'a'*64}
                with patch.object(package.subprocess,'run',return_value=types.SimpleNamespace(returncode=rc,stdout='probe output\n',stderr='')) as run:
                    if rc:
                        with self.assertRaises(AssertionError):package.probe_service(out,row,{})
                    else:self.assertEqual(package.probe_service(out,row,{}),oci.sha(out/'security-probe.json'))
                self.assertEqual(run.call_args.kwargs['input'],closure.PROBE)
                argv=run.call_args.args[0]
                for flag in ['--pull=never','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges']:self.assertIn(flag,argv)
                self.assertIn('/tmp:rw,nosuid,nodev,size=256m',argv)
                self.assertEqual(json.loads((out/'security-probe.json').read_text())['returncode'],rc)

    def test_old_service_receipt_is_not_reused(self):
        pins=json.loads((HERE/'pins.json').read_text())
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();source=root/'final/service';source.mkdir(parents=True)
            (source/'.wizard-source.json').write_text(json.dumps({'commit':pins['finalPins']['service']}))
            out=root/'image-packaging/service';out.mkdir(parents=True);(out/'recipe.json').write_text('{}')
            row={'sourceCommit':pins['finalPins']['service'],'ref':'ghcr.io/humanitylabs-org/wizard-agent-service','recipeSha256':oci.sha(out/'recipe.json')}
            (out/'result.json').write_text(json.dumps(row))
            with patch.object(package.sys,'argv',['package-image.py','--stage-root',str(root),'--component','service']),patch.object(package.sys,'platform','darwin'),patch.dict(os.environ,THALES_MEDIA=str(root)),patch.object(oci,'load') as load:
                with self.assertRaisesRegex(AssertionError,'unremediated/stale'):package.main()
            load.assert_not_called()

    def test_failed_service_probe_never_emits_success_receipt(self):
        pins=json.loads((HERE/'pins.json').read_text())
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();source=root/'final/service';source.mkdir(parents=True)
            (source/'.wizard-source.json').write_text(json.dumps({'commit':pins['finalPins']['service']}))
            (source/'Dockerfile').write_text('FROM node:22-alpine\nRUN apk add --no-cache python3 tini\nWORKDIR /app\nUSER 1000:1000\nENTRYPOINT ["/sbin/tini","--"]\nCMD ["node","server/index.mjs"]\n')
            def export(out,context,image,env,extra):
                text=(context/'Dockerfile').read_text()
                self.assertIn('COPY certifi.whl pip.whl remediate-trust.py',text)
                self.assertTrue(text.endswith('USER 1000:1000\n'))
                self.assertIn('ENTRYPOINT ["/sbin/tini","--"]',text)
                return {'archive':str(out/'image.oci.tar')},{'Config':{'Labels':{'org.opencontainers.image.revision':pins['finalPins']['service']}}}
            with contextlib.ExitStack() as s:
                s.enter_context(patch.object(package.sys,'argv',['package-image.py','--stage-root',str(root),'--component','service']))
                s.enter_context(patch.object(package.sys,'platform','darwin'));s.enter_context(patch.dict(os.environ,THALES_MEDIA=str(root)))
                s.enter_context(patch.object(oci,'environment',return_value={}))
                s.enter_context(patch.object(oci,'mirror',return_value='mirror.gcr.io/library/node@sha256:'+'a'*64))
                # Imported helper is a fresh module: intercept only its download, retain real recipe logic.
                real_module=package.module
                s.enter_context(patch.object(package,'module',side_effect=lambda name,file:types.SimpleNamespace(wheel=lambda *_:None) if file=='package-security-image.py' else real_module(name,file)))
                s.enter_context(patch.object(oci,'export',side_effect=export))
                s.enter_context(patch.object(package,'probe_service',side_effect=AssertionError('fixture probe failure')))
                with self.assertRaisesRegex(AssertionError,'fixture probe failure'):package.main()
            self.assertFalse((root/'image-packaging/service/result.json').exists())

if __name__=='__main__':unittest.main()
