"""Owning package/update wiring guards, not Docker or factory execution."""
import importlib.util,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
s=importlib.util.spec_from_file_location('voice_packaging_recipe',HERE/'package-voice-image.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Packaging(unittest.TestCase):
    def test_only_selected_base_and_source(self):
        text=(HERE/'package-voice-image.py').read_text()
        self.assertIn('voice_oci.derive(original,archive',text)
        self.assertNotIn("'pull'",text);self.assertNotIn('oci.export(',text)
    def test_base_receipt_is_immutable(self):
        text=(HERE/'package-voice-image.py').read_text();self.assertIn('702014b5df665c452e95adc5857d99b4d6a2af424edf68d8fe564217c5d9c213',text)
    def test_only_new_image_loaded(self):
        text=(HERE/'package-voice-image.py').read_text();self.assertEqual(text.count('oci.load('),1)
        self.assertIn('oci.load(root,transport',text)
    def test_factory_owns_overlay(self):
        text=(HERE/'package-security-image.py').read_text();self.assertIn("target.get('voiceOverlay')",text);self.assertIn("assert a.target=='transcriber'",text)
    def test_normal_final_selection_matches(self):
        self.assertIn("PREP/'voice-selected-engine.json'",(HERE/'guest-security-apply.py').read_text())
if __name__=='__main__':unittest.main()
