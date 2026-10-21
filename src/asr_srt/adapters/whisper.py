"""CPU Whisper engines operating exclusively on prepared local files."""

from contextlib import contextmanager
import math
import time

from .base import ASRAdapter, AdapterProgress
from ..domain import TextUnit, Transcript, TranscriptMetadata
from ..errors import DependencyError, ModelOutputError, ValidationError
from ..registry import execution, validate_options


def timestamped_units(parts, duration_ms):
    units = []
    for text, start, end in parts:
        if not text or not text.strip():
            continue
        if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start):
            raise ModelOutputError("Whisper returned missing or invalid segment timestamps")
        start_ms, end_ms = round(start * 1000), min(duration_ms, round(end * 1000))
        if start_ms >= duration_ms or end_ms <= start_ms:
            raise ModelOutputError("Whisper returned timestamps outside the audio duration")
        if units and start_ms < units[-1].start_ms:
            raise ModelOutputError("Whisper returned unordered segment timestamps")
        units.append(TextUnit(text.strip(), start_ms, end_ms))
    return tuple(units)


def whisper_language(value):
    return {"中文": "zh", "國語": "zh", "華語": "zh", "zh-TW": "zh", "zh-tw": "zh",
            "英文": "en", "自動": None, "auto": None}.get(value, value)


class LocalWhisperAdapter(ASRAdapter):
    progress_scope = "whole-input"

    def __init__(self, definition, root, model_factory=None):
        self.definition = definition
        self.spec = execution(definition)
        self.root, self.model_factory = root, model_factory
        self.model_id = definition["id"]
        self.model_revision = definition.get("snapshot_id", "local")

    def _load(self):
        engine, params = self.spec["engine"], self.spec["parameters"]
        if self.model_factory:
            return self.model_factory(model=self.root, device="cpu", local_files_only=True,
                                      engine=engine, parameters=dict(params))
        try:
            if engine == "faster-whisper":
                from faster_whisper import WhisperModel
                return WhisperModel(self.root, device="cpu", compute_type=params.get("compute_type", "int8"),
                                    local_files_only=True)
            import torch
            from transformers import WhisperProcessor, WhisperForConditionalGeneration, AutomaticSpeechRecognitionPipeline
            processor = WhisperProcessor.from_pretrained(self.root, local_files_only=True)
            model = WhisperForConditionalGeneration.from_pretrained(
                self.root, local_files_only=True, torch_dtype=torch.float32, use_safetensors=True).to("cpu").eval()
            return AutomaticSpeechRecognitionPipeline(model=model, tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor, device=-1, chunk_length_s=0)
        except ImportError as error:
            raise DependencyError(f"Missing local {engine} runtime. Install the project dependencies or rebuild the App.") from error

    @contextmanager
    def open_session(self, device, stage_callback=None):
        if device != "cpu":
            raise ValidationError(f"{self.model_id} supports CPU only")
        started = time.monotonic()
        try:
            model = self._load()
            if stage_callback:
                stage_callback("model-load", time.monotonic() - started)
            yield _WhisperSession(self, model)
        except MemoryError as error:
            raise DependencyError("Not enough memory to run this model. Close other applications and retry.") from error

    def transcribe(self, request):
        with self.open_session(request.device, request.stage_callback) as session:
            return session.transcribe(request)


class _WhisperSession:
    def __init__(self, adapter, model):
        self.adapter, self.model = adapter, model

    def transcribe(self, request):
        validate_options(self.adapter.definition, request.device, request.hotwords)
        started = time.monotonic()
        params = self.adapter.spec["parameters"]
        language = whisper_language(request.language)
        if self.adapter.spec["engine"] == "faster-whisper":
            segments, _ = self.model.transcribe(str(request.audio_path), language=language,
                beam_size=params.get("beam_size", 5), word_timestamps=True, vad_filter=False)
            parts = []
            for segment in segments:
                if segment.text.strip() and not segment.words:
                    raise ModelOutputError("Whisper returned text without word timestamps required for subtitle segmentation")
                parts.extend((word.word, word.start, word.end) for word in segment.words or [])
                if request.progress and segment.end > 0:
                    request.progress(AdapterProgress(min(segment.end * 1000, request.duration_ms),
                        request.duration_ms, "milliseconds", "whole-input", epoch=request.progress_epoch))
            units = timestamped_units(parts, request.duration_ms)
            text = "".join(part[0] for part in parts).strip()
        else:
            # Read the already normalized WAV locally, avoiding a pipeline subprocess
            # lookup of a system ffmpeg and keeping the bundled media boundary intact.
            import soundfile as sf
            audio, rate = sf.read(str(request.audio_path), dtype="float32")
            if rate != 16000 or audio.ndim != 1:
                raise ValidationError("Whisper requires normalized mono 16 kHz WAV")
            generate = {"task": "transcribe", "num_beams": params.get("num_beams", 1)}
            if language:
                generate["language"] = language
            raw = self.model({"raw": audio, "sampling_rate": rate}, return_timestamps="word", generate_kwargs=generate)
            text = raw.get("text", "").strip()
            parts = [(chunk.get("text", ""), *(chunk.get("timestamp") or (None, None))) for chunk in raw.get("chunks", [])]
            units = timestamped_units(parts, request.duration_ms)
            if text and not units:
                raise ModelOutputError("Whisper returned text without timestamps required for subtitles")
        if request.stage_callback:
            request.stage_callback("asr-inference", time.monotonic() - started)
        return Transcript(text, request.duration_ms, request.language, units,
            TranscriptMetadata(self.adapter.model_id, self.adapter.model_revision, request.device,
                request.hotwords, round(time.monotonic() - started, 3), request.cache_key))
