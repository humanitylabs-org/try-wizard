"""Owning package/update wiring guards, not Docker or factory execution."""
import importlib.util,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
s=importlib.util.spec_from_file_location('voice_packaging_recipe',HERE/'package-voice-image.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Packaging(unittest.TestCase):
    def test_only_selected_base_and_source(self):
        text=m.recipe('/app/.venv/lib/python3.12/site-packages/speaches/executors/parakeet.py','ubuntu')
        self.assertIn('FROM '+m.BASE,text);self.assertEqual(text.count('FROM '),1)
        self.assertIn('USER ubuntu',text);self.assertIn('parakeet.*.pyc',text)
        self.assertNotIn('apt',text);self.assertNotIn('pip ',text)
    def test_path_injection_refused(self):
        with self.assertRaises(AssertionError):m.recipe('/app/parakeet.py;evil','ubuntu')
    def test_root_runtime_refused(self):
        with self.assertRaises(AssertionError):m.recipe('/app/parakeet.py','root')
    def test_factory_owns_overlay(self):
        text=(HERE/'package-security-image.py').read_text();self.assertIn("target.get('voiceOverlay')",text);self.assertIn("assert a.target=='transcriber'",text)
    def test_normal_final_selection_matches(self):
        self.assertIn("PREP/'voice-selected-engine.json'",(HERE/'guest-security-apply.py').read_text())
if __name__=='__main__':unittest.main()
