"""Speech-to-text engines of the speech service, chosen by the model folder's ARTIFACT SET.

:mod:`agent_runtime.speech_service` loads one STT model from a local directory. Which engine
runs it is a fact about the files in that directory, never a config string: a NeMo TDT export
(``config.json`` naming ``nemo-conformer-tdt``, or its ``encoder-model*.onnx``) is Parakeet,
anything else is read as a Whisper ONNX export. :func:`engine_for` is the one place that
decides; the service, its status view, its admission estimate and its loader all read the
:class:`SttEngine` row it returns. Both engines run on onnx-asr over the speech pack's
onnxruntime, CPU only (owner ruling 2026-09-29: no ctranslate2, so no Intel OpenMP).

Parakeet TDT 0.6B v2 runs as the int8 ONNX export (the build the voice-model bench measured,
``docs/downstream/voice-model-bench-2026-09-28.md``) through onnx-asr on onnxruntime, CPU only.
onnx-asr is chosen over a sherpa-onnx build and over an own runner because it adds the least: a
7 MB pure-Python MIT package whose only hard requirement is numpy, on the onnxruntime the speech
pack already ships — no native build, no TTS code, no espeak-ng. It is loaded with an explicit
local directory and a model TYPE (never a Hub name), so its resolver runs offline and its
``huggingface_hub`` download branch is unreachable.

Parakeet is decoded in CHUNKS (:class:`ParakeetRunner`). Its encoder attends over the whole
input, so one pass over a long take costs time and memory in proportion to its length (measured
on the CPU path: 3.1 s and +0.95 GiB for 30 s of speech, 15.8 s and +1.9 GiB for 120 s). The
runner cuts the take in the quietest 200 ms inside the last :data:`CUT_SEARCH_SECONDS` before
every :data:`CHUNK_SECONDS` boundary and decodes each finished chunk ONCE (cached by its bytes),
so a partial or the final pass decodes only the open tail (< 10 s) whatever the take's length,
and the memory it holds is one chunk's.

Whisper runs the transformers.js ONNX export (``encoder_model_int8.onnx`` +
``decoder_model_merged_int8.onnx``, the layout onnx-asr's ``whisper`` type loads) through the
same chunking: Whisper's window is 30 s and onnx-asr's preprocessor cuts there, so a take of any
length is decoded 10 s at a time and a finished chunk once. onnx-asr loads the model and owns the
sessions, the log-mel features and the decoder step; :class:`WhisperDecoder` owns the greedy loop,
because onnx-asr's own ``recognize`` writes a language and a task token into the prompt, which an
English-only (``.en``) model was never trained on (measured on the bench's clips: empty text on
two of three). The loop also yields the no-speech probability and the mean log-probability
upstream's silence-hallucination gate reads, and a chunk with no speech-level energy is never
decoded (faster-whisper's VAD did that job before).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__layer__ = "stores"

__all__ = [
    "ChunkedRunner",
    "PARAKEET",
    "STT_ENGINES",
    "SttEngine",
    "WHISPER",
    "WhisperDecoder",
    "WhisperSegment",
    "chunk_cuts",
    "engine_for",
    "engine_importable",
    "load_parakeet",
    "load_whisper",
    "loudest_frame_dbfs",
    "missing_files",
    "nonempty",
    "unsupported_model_type",
]

WHISPER = "whisper-onnx"
PARAKEET = "parakeet-tdt"

#: The onnx-asr model type of a NeMo TDT export (its ``config.json`` ``model_type``).
PARAKEET_MODEL_TYPE = "nemo-conformer-tdt"
#: The onnx-asr model type of a Whisper export (transformers.js layout; its ``config.json`` says so).
WHISPER_MODEL_TYPE = "whisper"
#: The quantization the service loads for both engines: the int8 build, on CPU.
QUANTIZATION = "int8"

#: Parakeet chunking: a cut every CHUNK_SECONDS of audio, in the quietest 200 ms of the last
#: CUT_SEARCH_SECONDS before that boundary (an inter-word gap in practice).
CHUNK_SECONDS = 10
CUT_SEARCH_SECONDS = 4
_SAMPLE_RATE = 16000
_FRAME = _SAMPLE_RATE // 50  # 20 ms
_GAP_FRAMES = 10  # 200 ms


@dataclass(frozen=True)
class SttEngine:
    """One STT engine: the files that make a model folder complete, the imports that make the
    engine runnable, and its resident-memory estimate (``disk × factor + overhead``)."""

    name: str
    #: The ``config.json`` ``model_type`` this engine decodes (anything else is unsupported).
    model_type: str
    modules: tuple[str, ...]
    required: tuple[str, ...]
    #: At least one of these must be present and non-empty (``vocabulary.txt`` / ``.json``).
    one_of: tuple[str, ...] = ()
    disk_factor: float = 1.0
    overhead_bytes: int = 0
    #: A partial transcribes at most this much trailing audio (``None``: the whole take).
    partial_window_seconds: int | None = None


_MiB = 1024 * 1024

#: Resident-memory figures are measured on the CPU path (contract doc § Latency) and round up.
STT_ENGINES: dict[str, SttEngine] = {
    WHISPER: SttEngine(
        name=WHISPER, model_type=WHISPER_MODEL_TYPE, modules=("onnx_asr", "onnxruntime"),
        required=("config.json", "vocab.json", "added_tokens.json", f"encoder_model_{QUANTIZATION}.onnx",
                  f"decoder_model_merged_{QUANTIZATION}.onnx"),
        # Measured (contract doc § Latency): tiny.en int8 (40 MiB on disk) +172 MiB loaded,
        # +362 MiB after decoding; base.en (74 MiB) +224 / +482 MiB — onnxruntime's arenas grow
        # on the first decodes.
        disk_factor=3.5, overhead_bytes=240 * _MiB,
        # Chunked like Parakeet (module docstring): a partial covers the whole take.
        partial_window_seconds=None),
    PARAKEET: SttEngine(
        name=PARAKEET, model_type=PARAKEET_MODEL_TYPE, modules=("onnx_asr", "onnxruntime"),
        required=("config.json", "vocab.txt", f"encoder-model.{QUANTIZATION}.onnx",
                  f"decoder_joint-model.{QUANTIZATION}.onnx"),
        # Measured: +0.72 GiB loaded, +0.80 GiB after a 10 s chunk (weights 0.62 GiB on disk).
        disk_factor=1.0, overhead_bytes=256 * _MiB,
        # Finished chunks are cached, so a partial covers the whole take at the cost of its tail.
        partial_window_seconds=None),
}


def _config(path: Path) -> dict | None:
    """``config.json`` parsed, or ``None`` when absent, empty or not a JSON object."""
    try:
        value = json.loads((path / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def engine_for(path: Path) -> SttEngine:
    """The engine a model DIRECTORY is for, from its artifact set alone.

    Parakeet when the folder carries a NeMo TDT export's marker — ``config.json`` whose
    ``model_type`` is ``nemo-conformer-tdt``, or an ``encoder-model*.onnx`` — so a partial
    Parakeet download is still judged against Parakeet's file list. Otherwise Whisper (ONNX): a
    folder of the retired faster-whisper engine (``model.bin``) reads ``model_partial`` naming the
    ONNX files it lacks, and never reaches a loader.
    """
    config = _config(path) or {}
    if config.get("model_type") == PARAKEET_MODEL_TYPE or any(path.glob("encoder-model*.onnx")):
        return STT_ENGINES[PARAKEET]
    return STT_ENGINES[WHISPER]


def missing_files(engine: SttEngine, path: Path) -> list[str]:
    """The engine's files that are absent or empty in ``path``, and ``config.json`` when it does
    not parse (a torn download) — the ``missing`` list of a ``model_partial`` answer."""
    missing = [name for name in engine.required if not nonempty(path / name)]
    if engine.one_of and not any(nonempty(path / name) for name in engine.one_of):
        missing.append(engine.one_of[0])
    if "config.json" not in missing and _config(path) is None:
        missing.append("config.json")
    return missing


def unsupported_model_type(engine: SttEngine, path: Path) -> str | None:
    """A complete folder whose ``config.json`` ``model_type`` is not the one its engine decodes."""
    model_type = (_config(path) or {}).get("model_type")
    return None if model_type == engine.model_type else str(model_type)


def engine_importable(engine: SttEngine) -> bool:
    return all(importlib.util.find_spec(module) is not None for module in engine.modules)


def nonempty(path: Path) -> bool:
    """A regular file with at least one byte (a torn download often leaves a zero-byte file)."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


# ── loading (onnx-asr on onnxruntime, CPU) ──────────────────────────────────


def _load_onnx_asr(model_type: str, path: Path) -> Any:
    """onnx-asr's model in ``path``, int8, on the CPU provider. A model TYPE plus an existing
    local directory makes its resolver offline: nothing is resolved against a Hub."""
    import onnx_asr

    return onnx_asr.load_model(model_type, str(path), quantization=QUANTIZATION,
                               providers=["CPUExecutionProvider"])


def load_parakeet(path: Path) -> ChunkedRunner:
    """The int8 TDT export in ``path``, decoded chunk by chunk."""
    model = _load_onnx_asr(PARAKEET_MODEL_TYPE, path)
    return ChunkedRunner(lambda audio: str(model.recognize(audio, sample_rate=_SAMPLE_RATE)).strip())


def load_whisper(path: Path, *, keep: Callable[[WhisperSegment], bool] | None = None) -> ChunkedRunner:
    """The int8 Whisper export in ``path``, decoded chunk by chunk by :class:`WhisperDecoder`;
    ``keep`` is the caller's confidence gate over each chunk's segment."""
    return ChunkedRunner(WhisperDecoder(_load_onnx_asr(WHISPER_MODEL_TYPE, path).asr, keep=keep))


def chunk_cuts(samples: Any) -> list[int]:
    """Sample offsets where a take of int16 ``samples`` is cut: one per :data:`CHUNK_SECONDS`
    boundary the take has passed, each in the middle of the quietest 200 ms of the
    :data:`CUT_SEARCH_SECONDS` before it. A cut depends only on audio at or before its boundary,
    so the cuts of a growing take never move."""
    import numpy as np

    cuts, start = [], 0
    chunk, search = CHUNK_SECONDS * _SAMPLE_RATE, CUT_SEARCH_SECONDS * _SAMPLE_RATE
    while len(samples) - start >= chunk:
        region = samples[start + chunk - search:start + chunk].astype(np.float32)
        energy = np.square(region[:len(region) // _FRAME * _FRAME]).reshape(-1, _FRAME).sum(axis=1)
        # The quietest 200 ms span, not the quietest frame: a stop consonant's closure is a
        # silent 20 ms inside a word.
        span = np.convolve(energy, np.ones(_GAP_FRAMES), mode="valid")
        start = start + chunk - search + (int(np.argmin(span)) + _GAP_FRAMES // 2) * _FRAME
        cuts.append(start)
    return cuts


class ChunkedRunner:
    """A take decoded chunk by chunk (module docstring § chunks) by ``recognize``, which turns one
    chunk of 16 kHz float32 samples into text.

    ``transcribe`` is called with the whole take so far, by the service's single STT worker;
    each finished chunk's text is cached by the chunk's bytes (a few dozen entries), so a take
    that grows between passes re-decodes only its open tail.
    """

    CACHE_ENTRIES = 64

    def __init__(self, recognize: Callable[[Any], str]) -> None:
        self.recognize = recognize
        self._texts: OrderedDict[bytes, str] = OrderedDict()
        self._lock = threading.Lock()

    def transcribe(self, pcm: bytes) -> str:
        """16 kHz mono ``pcm_s16le`` -> text. Both engines decode greedily, so a partial and a
        final pass are the same computation."""
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16)
        bounds = [0, *chunk_cuts(samples), len(samples)]
        texts = [self._chunk_text(samples[a:b], cached=b != len(samples))
                 for a, b in zip(bounds, bounds[1:]) if b > a]
        return " ".join(t for t in texts if t)

    def _chunk_text(self, samples: Any, *, cached: bool) -> str:
        key = hashlib.blake2b(samples.tobytes(), digest_size=16).digest()
        with self._lock:
            if key in self._texts:
                self._texts.move_to_end(key)
                return self._texts[key]
        text = self.recognize(samples.astype("float32") / 32768.0)
        if cached:  # the open tail changes on every pass: never worth a slot
            with self._lock:
                self._texts[key] = text
                while len(self._texts) > self.CACHE_ENTRIES:
                    self._texts.popitem(last=False)
        return text


# ── Whisper (onnx-asr's export loader and decoder step, our greedy loop) ────


#: A chunk whose loudest 20 ms frame is quieter than this (RMS, dBFS) holds no speech and is not
#: decoded: over silence Whisper writes "you" with a confident log-probability, which upstream's
#: AND gate keeps. Speech at a normal distance sits 20-30 dB above it.
SILENCE_DBFS = -45.0
#: The most tokens one chunk decodes (Whisper's own ``sample_len``: half its text context).
MAX_TOKENS = 224
#: A whole-chunk non-speech caption (``[BLANK_AUDIO]``, ``(music)``): Whisper saying "nothing
#: was said".
_CAPTION = re.compile(r"\s*[\[(][^\])]*[\])]\s*")
#: Whisper's multilingual vocabulary; an English-only (``.en``) model has one token fewer.
_MULTILINGUAL_VOCAB = 51865


@dataclass(frozen=True)
class WhisperSegment:
    """One decoded chunk, in the shape upstream's silence-hallucination gate reads."""

    text: str
    no_speech_prob: float
    avg_logprob: float


def loudest_frame_dbfs(audio: Any) -> float:
    """The RMS level, in dBFS, of the loudest 20 ms frame of float32 ``audio`` in [-1, 1]."""
    import numpy as np

    frames = audio[:len(audio) // _FRAME * _FRAME].astype(np.float64).reshape(-1, _FRAME)
    if not len(frames):
        return float("-inf")
    peak = float(np.sqrt(np.square(frames).mean(axis=1)).max())
    return 20 * float(np.log10(peak)) if peak > 0 else float("-inf")


class WhisperDecoder:
    """Greedy Whisper decoding over onnx-asr 0.12.0's ``WhisperHf`` (its encoder, its decoder step
    with the key/value cache, its token tables), with the prompt the model was trained on:
    ``<|startoftranscript|><|notimestamps|>`` for an English-only model, ``<|en|><|transcribe|>``
    between them for a multilingual one (the service is English-only).
    """

    def __init__(self, asr: Any, *, keep: Callable[[WhisperSegment], bool] | None = None) -> None:
        tokens = asr._tokens
        english_only = int(asr.config.get("vocab_size", _MULTILINGUAL_VOCAB)) < _MULTILINGUAL_VOCAB
        self.asr, self.keep = asr, keep
        self.prompt = [tokens["<|startoftranscript|>"],
                       *(() if english_only else (tokens["<|en|>"], tokens["<|transcribe|>"])),
                       tokens["<|notimestamps|>"]]
        self.no_speech = tokens["<|nospeech|>"] if "<|nospeech|>" in tokens else tokens["<|nocaptions|>"]
        self.eos = tokens["<|endoftext|>"]

    def __call__(self, audio: Any) -> str:
        """One chunk of 16 kHz float32 samples -> its text, or ``""`` when it holds no speech."""
        if loudest_frame_dbfs(audio) < SILENCE_DBFS:
            return ""
        segment = self.decode(audio)
        if not segment.text or _CAPTION.fullmatch(segment.text):
            return ""
        if self.keep is not None and not self.keep(segment):
            return ""
        return segment.text

    def decode(self, audio: Any) -> WhisperSegment:
        import numpy as np

        waveforms = audio[None, :].astype(np.float32)
        encoded = self.asr._encode(waveforms, np.array([waveforms.shape[1]], dtype=np.int64))
        tokens = np.array([self.prompt], dtype=np.int64)
        state = self.asr._create_state()
        logprobs: list[float] = []
        no_speech = 0.0
        for step in range(MAX_TOKENS):
            logits, state = self.asr._decode(tokens, state, encoded)
            if step == 0:  # the no-speech probability is read at the start-of-transcript position
                no_speech = float(np.exp(_log_softmax(logits[0, 0])[self.no_speech]))
            scores = _log_softmax(logits[0, -1])
            token = int(scores.argmax())
            logprobs.append(float(scores[token]))
            if token == self.eos:
                break
            tokens = np.hstack((tokens, np.array([[token]], dtype=np.int64)))
        text = self.asr._decode_tokens(tokens[0, len(self.prompt):]).text.strip()
        return WhisperSegment(text, no_speech, float(np.mean(logprobs)))


def _log_softmax(logits: Any) -> Any:
    import numpy as np

    shifted = logits.astype(np.float64) - float(logits.max())
    return shifted - float(np.log(np.exp(shifted).sum()))
