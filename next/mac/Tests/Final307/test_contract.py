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
    def test_source_unchanged_contract(self):
        root=P.parents[4]
        source=(root/'next/mac/App/WizardUpdater.swift').read_text()
        self.assertIn('func admitLegacyBootstrap() -> Bool',source)
        self.assertIn('Activity changed while confirming; upgrade deferred',source)
        self.assertIn('Unknown legacy boot files',source)
        self.assertIn('Not now',source)

if __name__ == '__main__':unittest.main()
