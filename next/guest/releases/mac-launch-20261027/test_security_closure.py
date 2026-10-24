#!/usr/bin/env python3
"""Control-plane tests, deliberately synthetic fixtures; no Docker/VM/acceptance/network probes."""
import hashlib, importlib.util, json, os, re, ssl, subprocess, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file);assert spec and spec.loader
    out=importlib.util.module_from_spec(spec);spec.loader.exec_module(out);return out
closure=module('closure_contract','security-closure.py');probe=module('probe_contract','security-probe.py');remediate=module('remediate_contract','remediate-trust.py');package=module('package_contract','package-security-image.py')

class SecurityTests(unittest.TestCase):
    def test_complete_immutable_selection(self):
        plan=json.loads((HERE/'security-image-plan.json').read_text())
        self.assertEqual(len(plan['targets']),17);self.assertEqual(sum(t['resolution']=='derive-image' for t in plan['targets']),14)
        self.assertTrue(plan['selectionComplete']);self.assertFalse(plan['complete'])
        for row in plan['targets']:
            if row['resolution']=='derive-image':
                if row.get('baseComponent'):
                    self.assertEqual(row['sourceCommit'],json.loads((HERE/'pins.json').read_text())['finalPins'][row['baseComponent']])
                    self.assertEqual(row['baseRef'],'ghcr.io/humanitylabs-org/wizard-recorder')
                    self.assertNotIn('base',row)  # No private-registry fallback.
                else:self.assertRegex(row['base'],r'^.+@sha256:[0-9a-f]{64}$')
    def test_all_fourteen_advisory_hosts(self):
        self.assertEqual(len(probe.BAD),14);self.assertEqual(len(set(probe.BAD)),14)
        self.assertIn('dv-g3b-noct-emudhra',probe.BAD);self.assertIn('dv-g3b-aaa-noct-emudhra',probe.BAD)
    def test_node_per_major_thresholds(self):
        for text in ['22.23.4','24.22.1','26.12.1']:self.assertTrue(probe.node_supported(text),text)
        for text in ['22.23.3','24.22.0','26.12.0','26.5.1','20.20.0','28.0.0']:self.assertFalse(probe.node_supported(text),text)
    def test_missing_receipt_never_resolves(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(FileNotFoundError):closure.resolve_plan(json.loads((HERE/'security-image-plan.json').read_text()),Path(t),json.loads((HERE/'pins.json').read_text()))
    def test_duplicate_target_refused(self):
        plan=json.loads((HERE/'security-image-plan.json').read_text());plan['targets'][1]=plan['targets'][0]
        with self.assertRaises(AssertionError):closure.resolve_plan(plan,Path('/not-used'),{})
    def test_shell_is_syntactically_valid(self):
        subprocess.run(['sh','-n'],input=closure.PROBE,text=True,check=True)
        self.assertIn('test "$rc" = 60',closure.PROBE)
        self.assertIn('SSLCertVerificationError',closure.PROBE)
        self.assertIn('/opt/hermes/.venv/bin/python',closure.PROBE)
    def test_no_abi_replacement_needed_for_python_certificate_incident(self):
        source=(HERE/'remediate-trust.py').read_text()
        self.assertIn('ensurepip',source);self.assertNotIn('uv python install',source)
        self.assertIn('26.2.2',source)
    def test_vendor_and_ensurepip_are_not_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);vendor=root/'venv/lib/site-packages/pip/_vendor/certifi';vendor.mkdir(parents=True)
            (vendor/'cacert.pem').write_text('unit obsolete');(vendor/'__init__.py').write_text('__version__="2000.1.1"')
            wheel=root/'certifi.whl'
            with zipfile.ZipFile(wheel,'w') as z:
                z.writestr('certifi/__init__.py','__version__="2026.10.19"');z.writestr('certifi/cacert.pem','unit replacement')
            patched=remediate.patch_certifi(wheel,[str(root)])
            self.assertEqual(patched,[str(vendor)]);self.assertEqual((vendor/'cacert.pem').read_text(),'unit replacement')
    def test_pip_and_ensurepip_wheel_upgrade(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);site=root/'venv/site-packages';(site/'pip').mkdir(parents=True)
            (site/'pip/__init__.py').write_text('__version__="old"');(site/'pip-1.0.dist-info').mkdir()
            ensure=root/'stdlib/ensurepip';(ensure/'_bundled').mkdir(parents=True)
            (ensure/'__init__.py').write_text('_PIP_VERSION = "1.0"\n');(ensure/'_bundled/pip-1.0.whl').write_text('unit old')
            wheel=root/'fixed.whl'
            with zipfile.ZipFile(wheel,'w') as z:
                z.writestr('pip/__init__.py','__version__="26.2.2"');z.writestr('pip-26.2.2.dist-info/METADATA','unit fixture')
            result=remediate.patch_pip(wheel,[str(root)])
            self.assertEqual(result['pipCopies'],[str(site/'pip')]);self.assertEqual(result['ensurepipCopies'],[str(ensure)])
            self.assertFalse((site/'pip-1.0.dist-info').exists());self.assertEqual([p.name for p in (ensure/'_bundled').iterdir()],['pip-26.2.2-py3-none-any.whl'])
            self.assertIn('26.2.2',(ensure/'__init__.py').read_text())
    def test_unknown_ensurepip_contract_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'ensurepip').mkdir();(root/'ensurepip/__init__.py').write_text('unknown')
            wheel=root/'fixed.whl'
            with zipfile.ZipFile(wheel,'w') as z:z.writestr('pip/__init__.py','__version__="26.2.2"')
            with self.assertRaises(AssertionError):remediate.patch_pip(wheel,[str(root)])
    def test_source_and_runtime_identity_preserved_in_recipe(self):
        plan=json.loads((HERE/'security-image-plan.json').read_text());base=plan['targets'][0]['base']
        source=package.recipe(base,{'User':'1000:1000'},{'nodeMajor':26,'alpine':False,'claude':True},plan)
        self.assertIn('26.12.1',source);self.assertTrue(source.endswith('USER 1000:1000\n'));self.assertNotIn('ENTRYPOINT',source)
        self.assertIn('@anthropic-ai/claude-code@2.1.303',source);self.assertIn('--pip-wheel',source)
    def test_no_node_copy_for_python_helper(self):
        plan=json.loads((HERE/'security-image-plan.json').read_text());source=package.recipe(plan['targets'][0]['base'],{}, {'nodeMajor':0,'alpine':True,'claude':False},plan)
        self.assertNotIn('fixed_node',source);self.assertIn('apk add',source)
        self.assertNotIn('p11-kit',source);self.assertNotIn('--browser-evidence',source)
    def test_any_discovered_browser_gets_system_nss_distrust(self):
        plan=json.loads((HERE/'security-image-plan.json').read_text())
        for alpine,packages in [(False,'p11-kit p11-kit-modules'),(True,'p11-kit p11-kit-trust')]:
            source=package.recipe('unit.invalid/not-named-browser@sha256:'+'a'*64,{'User':'1000'}, {'nodeMajor':0,'alpine':alpine,'claude':False,'browser':True},plan)
            self.assertIn(packages,source);self.assertIn('COPY security-primary-evidence.json',source)
            self.assertIn('--browser-evidence /opt/wizard-security/security-primary-evidence.json',source)
            self.assertTrue(source.endswith('USER 1000\n'));self.assertNotIn('ENTRYPOINT',source)
        subprocess.run(['sh','-n'],input=package.INVENTORY,text=True,check=True)
        for binary in ['headless-shell','headless_shell','chromium','chromium-browser','google-chrome']:
            self.assertIn(binary,package.INVENTORY)
    def test_browser_distrust_validates_real_der_and_complete_advisory_set(self):
        evidence=HERE/'security-primary-evidence.json'
        self.assertEqual({f for f,_ in remediate.browser_certificates(evidence)},remediate.BLOCKED)
        original=json.loads(evidence.read_text())
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'evidence.json'
            for change in ['fingerprint','missing','duplicate']:
                data=json.loads(json.dumps(original))
                if change=='fingerprint':data['roots']['data'][0]['sha256']='0'*64
                elif change=='missing':data['roots']['data'].pop()
                else:data['roots']['data'].append(data['roots']['data'][0])
                path.write_text(json.dumps(data))
                with self.assertRaises(AssertionError):remediate.browser_certificates(path)
    def test_minimal_files_uses_fixed_helper_not_a_fake_package_manager(self):
        plan=json.loads((HERE/'security-image-plan.json').read_text());plan['_helperImage']='unit.invalid/helper@sha256:'+'a'*64
        base=next(t['base'] for t in plan['targets'] if t['key']=='files')
        source=package.recipe(base,{'User':'user'},{'minimal':True},plan)
        self.assertIn('AS security_tools',source);self.assertNotIn('apt-get',source);self.assertNotIn('apk add',source)
        self.assertIn('--output /opt/wizard-security/remediation.json',source)
    def test_unknown_minimal_image_is_not_exempted(self):
        with self.assertRaises(AssertionError):package.recipe('unit.invalid/unknown@sha256:'+'f'*64,{}, {'minimal':True},{})
    def test_compose_binding_covers_every_real_default_service(self):
        bindings=json.loads((HERE/'security-compose-bindings.json').read_text())['bindings']
        self.assertEqual(len(bindings),17)
        self.assertEqual(sum(b['target']=='helper-python' for b in bindings),8)
        self.assertEqual(len({(b['app'],b['service']) for b in bindings}),17)
    def test_application_never_exempts_unmapped_images(self):
        source=(HERE/'guest-security-apply.py').read_text()
        self.assertIn('unplanned running image',source);self.assertIn('unplanned inherited/cached image retained',source)
        self.assertIn("assert not Path('/var/lib/wizard/setup.json').exists()",source)
    def test_explicit_no_security_deferrals(self):
        plan=json.loads((HERE/'security-image-plan.json').read_text())
        self.assertTrue(all(r['resolution'] in {'derive-image','replace-and-remove','patch-guest-host'} for r in plan['findings']))

if __name__=='__main__':unittest.main()
