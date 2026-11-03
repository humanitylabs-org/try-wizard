"""Tiny source fakes for real adapter functions. NOT ARM/runtime acceptance."""
import ast, contextlib, hashlib, json, tempfile, types, unittest
from pathlib import Path
from unittest.mock import MagicMock

HERE=Path(__file__).resolve().parents[1]
SOURCE=HERE/'voice-parakeet.py'

class Generic:
    @classmethod
    def __class_getitem__(cls,key): return cls
    def __init__(self,*args,**kwargs): pass

class Adapter(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.cache=Path(self.temp.name)
        tree=ast.parse(SOURCE.read_text());tree.body=[n for n in tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
        self.api=types.SimpleNamespace(Transcription=lambda **kw:kw,TranscriptionVerbose=lambda **kw:kw)
        self.onnx=types.SimpleNamespace(load_model=MagicMock(return_value='adapter'))
        self.g={'Path':Path,'hashlib':hashlib,'HF_HUB_CACHE':str(self.cache),'onnx_asr':self.onnx,
            'Generator':__import__('typing').Generator,'TypedDict':__import__('typing').TypedDict,'TextResultsAsrAdapter':object,
            'Model':lambda **kw:kw,'OrtOptions':object,'BaseModelManager':Generic,'ModelRegistry':Generic,
            'get_ort_providers_with_options':lambda x:['CPUExecutionProvider'],
            'TranscriptionRequest':object,'NonStreamingTranscriptionResponse':object,'StreamingTranscriptionEvent':object,
            'HfModelFilter':lambda **kw:kw,'traced':lambda:lambda x:x,'traced_generator':lambda:lambda x:x,
            'openai':types.SimpleNamespace(types=types.SimpleNamespace(audio=self.api))}
        exec(compile(tree,str(SOURCE),'exec'),self.g)
        self.pins=self.g['FILES'].copy()
        self.snapshot=self.cache/'models--istupakov--parakeet-tdt-0.6b-v2-onnx'/'snapshots'/self.g['REVISION'];self.snapshot.mkdir(parents=True)
        self.g['FILES']={n:(len(n.encode()),hashlib.sha256(n.encode()).hexdigest()) for n in self.pins}
        for n in self.pins:(self.snapshot/n).write_text(n)
    def validate(self):return self.g['validated_snapshot'](self.g['MODEL_ID'])
    def test_real_pins_unchanged(self):
        self.assertEqual(self.pins['encoder-model.int8.onnx'],(652184014,'3e0581fda6ab843888b51e56d7ee78b6d5bc3237ec113af1f732d1d5286aa155'))
        self.assertEqual(len(self.pins),4)
    def test_correct_snapshot(self):self.assertEqual(self.validate(),self.snapshot)
    def test_mutable_main_not_used(self):
        refs=self.snapshot.parent.parent/'refs';refs.mkdir();(refs/'main').write_text('wrong');self.validate()
    def test_wrong_revision(self):
        self.snapshot.rename(self.snapshot.with_name('wrong'))
        with self.assertRaises(ValueError):self.validate()
    def test_extra_glob_variant(self):
        (self.snapshot/'encoder-model_int8.onnx').touch()
        with self.assertRaises(ValueError):self.validate()
    def test_fp32_rejected(self):
        (self.snapshot/'encoder-model.onnx').touch()
        with self.assertRaises(ValueError):self.validate()
    def test_external_data_rejected(self):
        (self.snapshot/'encoder-model.int8.onnx.data').touch()
        with self.assertRaises(ValueError):self.validate()
    def test_corrupt_bytes(self):
        n='config.json';(self.snapshot/n).write_text('x'*len(n))
        with self.assertRaises(ValueError):self.validate()
    def test_escaping_symlink(self):
        n='vocab.txt';(self.cache/n).write_text(n);(self.snapshot/n).unlink();(self.snapshot/n).symlink_to(self.cache/n)
        with self.assertRaises(ValueError):self.validate()
    def test_blob_symlink_allowed(self):
        n='vocab.txt';blobs=self.snapshot.parent.parent/'blobs';blobs.mkdir();(blobs/'digest').write_text(n)
        (self.snapshot/n).unlink();(self.snapshot/n).symlink_to(blobs/'digest');self.validate()
    def test_exact_local_loader(self):
        manager=self.g['ParakeetModelManager'](5,object());self.assertEqual(manager._load_fn(self.g['MODEL_ID']),'adapter')
        self.onnx.load_model.assert_called_once_with('nemo-conformer-tdt',path=self.snapshot,quantization='int8',providers=['CPUExecutionProvider'])
    def test_unknown_model_no_load(self):
        with self.assertRaises(ValueError):self.g['ParakeetModelManager'](5,object())._load_fn('other/model')
        self.onnx.load_model.assert_not_called()
    def test_registry_exact_files(self):
        files=self.g['parakeet_model_registry'].get_model_files(self.g['MODEL_ID']);self.assertEqual(files['encoder'].name,'encoder-model.int8.onnx')
    def test_registry_local_only(self):
        registry=self.g['parakeet_model_registry'];self.assertEqual(list(registry.list_remote_models()),[])
        self.assertEqual([v['id'] for v in registry.list_local_models()],[self.g['MODEL_ID']])
        with self.assertRaises(ValueError):registry.download_model_files(self.g['MODEL_ID'])
    def test_corrupt_not_listed(self):
        (self.snapshot/'vocab.txt').unlink();self.assertEqual(list(self.g['parakeet_model_registry'].list_local_models()),[])
    def transcribe(self,format,language='en'):
        manager=self.g['ParakeetModelManager'](5,object())
        decoder=MagicMock();decoder.with_timestamps.return_value.recognize.return_value=types.SimpleNamespace(text='blue lantern')
        manager.load_model=lambda m:contextlib.nullcontext(decoder)
        request=types.SimpleNamespace(response_format=format,model=self.g['MODEL_ID'],language=language,audio=types.SimpleNamespace(data=[],duration=2.5))
        return manager.handle_non_streaming_transcription_request(request)
    def test_verbose_normal_route_format(self):self.assertEqual(self.transcribe('verbose_json'),{'text':'blue lantern','language':'en','duration':2.5})
    def test_json_text_parity(self):self.assertEqual(self.transcribe('json')['text'],self.transcribe('text')[0])
    def test_nonenglish_refused(self):
        with self.assertRaises(ValueError):self.transcribe('verbose_json','de')
    def test_unsupported_format(self):
        with self.assertRaises(ValueError):self.transcribe('srt')

if __name__=='__main__':unittest.main()
