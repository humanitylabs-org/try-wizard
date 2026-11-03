"""Pinned local Parakeet adapter for the security-selected Speaches 0.9 image.
No remote model lookup, mutable revision, alternate graph or provider fallback.
"""
from collections.abc import Generator
import hashlib
from pathlib import Path
from typing import TypedDict

from huggingface_hub.constants import HF_HUB_CACHE
import onnx_asr
from onnx_asr.adapters import TextResultsAsrAdapter
import openai.types.audio
from speaches.api_types import Model
from speaches.config import OrtOptions
from speaches.executors.shared.base_model_manager import BaseModelManager, get_ort_providers_with_options
from speaches.executors.shared.handler_protocol import NonStreamingTranscriptionResponse, StreamingTranscriptionEvent, TranscriptionRequest
from speaches.hf_utils import HfModelFilter
from speaches.model_registry import ModelRegistry
from speaches.tracing import traced, traced_generator

MODEL_ID = 'istupakov/parakeet-tdt-0.6b-v2-onnx'
REVISION = '0bbb45a3365852604aef28b538a8f066f4ccaa85'
WIZARD_PINNED_PARAKEET = 1
TASK_NAME_TAG = 'automatic-speech-recognition'
FILES = {
    'encoder-model.int8.onnx': (652184014, '3e0581fda6ab843888b51e56d7ee78b6d5bc3237ec113af1f732d1d5286aa155'),
    'decoder_joint-model.int8.onnx': (8998286, 'a449f49acd68979d418651dd2dcb737cc0f1bf0225e009e29ee326354edbf7d3'),
    'vocab.txt': (9384, 'ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d'),
    'config.json': (97, '666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466'),
}
hf_model_filter = HfModelFilter(model_name='istupakov/parakeet-tdt', task=TASK_NAME_TAG)


def validated_snapshot(model_id):
    if model_id != MODEL_ID:
        raise ValueError('Only the security-selected local Parakeet model is supported')
    repo = Path(HF_HUB_CACHE)/'models--istupakov--parakeet-tdt-0.6b-v2-onnx'
    snapshot = repo/'snapshots'/REVISION
    # Select the immutable snapshot explicitly. refs/main is deliberately unused.
    for directory in (repo, repo/'snapshots', snapshot):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Pinned Parakeet snapshot is unavailable or redirected')
    names = {p.name for p in snapshot.iterdir()}
    if not set(FILES) <= names or names - {*FILES, 'README.md'}:
        raise ValueError('Pinned Parakeet snapshot has missing or unexpected artifacts')
    blobs = repo/'blobs'
    if blobs.is_symlink():
        raise ValueError('Pinned Parakeet blob store is redirected')
    for name, (size, digest) in FILES.items():
        path = snapshot/name
        resolved = path.resolve(strict=True)
        if path.is_symlink() and resolved.parent != blobs.resolve():
            raise ValueError('Pinned Parakeet artifact escapes its blob store')
        if not resolved.is_file() or resolved.stat().st_size != size:
            raise ValueError('Pinned Parakeet artifact size mismatch')
        with resolved.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('Pinned Parakeet artifact digest mismatch')
    return snapshot


class NemoConformerTdtModelFiles(TypedDict):
    encoder: Path
    decoder_joint: Path
    vocab: Path
    config: Path


class NemoConformerTdtModelRegistry(ModelRegistry[Model, NemoConformerTdtModelFiles]):
    def list_remote_models(self) -> Generator[Model]:
        yield from ()

    def list_local_models(self) -> Generator[Model]:
        try:
            validated_snapshot(MODEL_ID)
        except (OSError, ValueError):
            return
        yield Model(id=MODEL_ID, created=0, owned_by='istupakov', language=['en'], task=TASK_NAME_TAG)

    def get_model_files(self, model_id: str) -> NemoConformerTdtModelFiles:
        path = validated_snapshot(model_id)
        return NemoConformerTdtModelFiles(encoder=path/'encoder-model.int8.onnx',
            decoder_joint=path/'decoder_joint-model.int8.onnx', vocab=path/'vocab.txt', config=path/'config.json')

    def download_model_files(self, model_id: str) -> None:
        raise ValueError('Remote model download disabled; install the pinned local voice package')


parakeet_model_registry = NemoConformerTdtModelRegistry(hf_model_filter=hf_model_filter)


class ParakeetModelManager(BaseModelManager[TextResultsAsrAdapter]):
    def __init__(self, ttl: int, ort_opts: OrtOptions) -> None:
        super().__init__(ttl)
        self.ort_opts = ort_opts

    def _load_fn(self, model_id: str) -> TextResultsAsrAdapter:
        path = validated_snapshot(model_id)
        providers = get_ort_providers_with_options(self.ort_opts)
        # onnx-asr 0.7 uses glob '?int8': '?' correctly matches '.', not a
        # literal filename. Exact membership + hashes above remove ambiguity.
        return onnx_asr.load_model('nemo-conformer-tdt', path=path, quantization='int8', providers=providers)

    @traced()
    def handle_non_streaming_transcription_request(self, request: TranscriptionRequest, **_kwargs) -> NonStreamingTranscriptionResponse:
        if request.language not in (None, 'en'):
            raise ValueError('Pinned Parakeet supports English only')
        if request.response_format not in ('text', 'json', 'verbose_json'):
            raise ValueError(f"'{request.response_format}' response format is not supported for '{request.model}' model.")
        with self.load_model(request.model) as parakeet:
            results = parakeet.with_timestamps().recognize(request.audio.data)
            match request.response_format:
                case 'text':
                    return results.text, 'text/plain'
                case 'json':
                    return openai.types.audio.Transcription(text=results.text)
                case 'verbose_json':
                    # The fixed model is English. No invented segment/word timings.
                    return openai.types.audio.TranscriptionVerbose(text=results.text,
                        language='en', duration=request.audio.duration)

    @traced_generator()
    def handle_streaming_transcription_request(self, request: TranscriptionRequest, **_kwargs) -> Generator[StreamingTranscriptionEvent]:
        raise NotImplementedError(f"'{request.model}' model doesn't support streaming transcription.")

    def handle_transcription_request(self, request: TranscriptionRequest, **kwargs) -> NonStreamingTranscriptionResponse | Generator[StreamingTranscriptionEvent]:
        if request.stream:
            return self.handle_streaming_transcription_request(request, **kwargs)
        return self.handle_non_streaming_transcription_request(request, **kwargs)
