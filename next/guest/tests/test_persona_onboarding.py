"""Run in the stock engine with these three files staged together for QA."""
import contextlib,importlib.util,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import hermes_constants
from hermes_cli.default_soul import DEFAULT_SOUL_MD
ROOT=Path(__file__).parent
def module(name,file):
 s=importlib.util.spec_from_file_location(name,ROOT/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
brain=module('brain','hermes_brain.py');product=module('product','product_plugin.py')
class Persona(unittest.TestCase):
 def test_default_becomes_recipient_name(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'SOUL.md';p.write_text(DEFAULT_SOUL_MD)
   with patch.object(hermes_constants,'get_hermes_home',return_value=Path(d)),patch.object(sys,'stdin',io.StringIO(json.dumps({'name':'Aster QA'}))),contextlib.redirect_stdout(io.StringIO()):brain.soul()
   self.assertTrue(p.read_text().startswith('# Aster QA\n\nYou are Aster QA,'))
 def test_custom_persona_byte_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'SOUL.md';original=b'# Existing Name\n\nCustom persona stays byte-identical.\n';p.write_bytes(original)
   with patch.object(hermes_constants,'get_hermes_home',return_value=Path(d)),patch.object(sys,'stdin',io.StringIO(json.dumps({'name':'Replacement'}))),contextlib.redirect_stdout(io.StringIO()):brain.soul()
   self.assertEqual(p.read_bytes(),original)
 def test_product_context_uses_own_personal_name(self):
  with tempfile.TemporaryDirectory() as d:
   (Path(d)/'SOUL.md').write_text('# Aster QA\n\nYou are Aster QA, the user\'s personal wizard.\n')
   with patch.object(hermes_constants,'get_hermes_home',return_value=Path(d)):text=product.product_context(None)
   self.assertTrue(text.startswith('Personal identity from your own SOUL.md: your name is Aster QA.'))
   self.assertNotIn('You are Wizard,',text)
 def test_unrecognized_custom_document_not_name_parsed(self):
  with tempfile.TemporaryDirectory() as d:
   (Path(d)/'SOUL.md').write_text('# Preferences\n\nDo not turn a heading into a personal name.\n')
   with patch.object(hermes_constants,'get_hermes_home',return_value=Path(d)):text=product.product_context(None)
   self.assertFalse(text.startswith('Personal identity'))
if __name__=='__main__':unittest.main()
