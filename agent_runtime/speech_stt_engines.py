"""Speech-to-text engines of the speech service, chosen by the model folder's ARTIFACT SET.

:mod:`agent_runtime.speech_service` loads one STT model from a local directory. Which engine
runs it is a fact about the files in that directory, never a config string: a NeMo TDT export
(``config.json`` naming ``nemo-conformer-tdt``, or its ``encoder-model*.onnx``) is Parakeet,
anything else is read as a faster-whisper (CTranslate2) directory, the engine this service
started with. :func:`engine_for` is the one place that decides; the service, its status view,
its admission estimate and its loader all read the :class:`SttEngine` row it returns.

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
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__layer__ = "stores"

__all__ = [
    "PARAKEET",
    "ParakeetRunner",
    "STT_ENGINES",
    "SttEngine",
    "WHISPER",
    "engine_for",
    "engine_importable",
    "load_parakeet",
    "missing_files",
    "nonempty",
    "chunk_cuts",
    "transcribe_parakeet",
    "unsupported_model_type",
]

WHISPER = "faster-whisper"
PARAKEET = "parakeet-tdt"

#: The onnx-asr model type of a NeMo TDT export (its ``config.json`` ``model_type``).
PARAKEET_MODEL_TYPE = "nemo-conformer-tdt"
#: The quantization the service loads: the int8 build, on CPU.
PARAKEET_QUANTIZATION = "int8"

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
        name=WHISPER, modules=("faster_whisper",),
        required=("model.bin", "config.json", "tokenizer.json"),
        one_of=("vocabulary.txt", "vocabulary.json"),
        disk_factor=1.0, overhead_bytes=96 * _MiB,
        # whisper pads to a 30 s window, so a pass costs the same up to 30 s and a partial
        # stays flat on long takes by decoding only the last 30 s.
        partial_window_seconds=30),
    PARAKEET: SttEngine(
        name=PARAKEET, modules=("onnx_asr", "onnxruntime"),
        required=("config.json", "vocab.txt", f"encoder-model.{PARAKEET_QUANTIZATION}.onnx",
                  f"decoder_joint-model.{PARAKEET_QUANTIZATION}.onnx"),
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
    Parakeet download is still judged against Parakeet's file list. Otherwise faster-whisper.
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
    """A complete NeMo folder whose ``model_type`` is not the TDT this service decodes."""
    if engine.name != PARAKEET:
        return None
    model_type = (_config(path) or {}).get("model_type")
    return None if model_type == PARAKEET_MODEL_TYPE else str(model_type)


def engine_importable(engine: SttEngine) -> bool:
    return all(importlib.util.find_spec(module) is not None for module in engine.modules)


def nonempty(path: Path) -> bool:
    """A regular file with at least one byte (a torn download often leaves a zero-byte file)."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


# ── Parakeet (onnx-asr on onnxruntime, CPU) ─────────────────────────────────


def load_parakeet(path: Path) -> ParakeetRunner:
    """The int8 TDT export in ``path`` on the CPU provider. A model TYPE plus an existing local
    directory makes onnx-asr's resolver offline: nothing is resolved against a Hub."""
    import onnx_asr

    return ParakeetRunner(onnx_asr.load_model(PARAKEET_MODEL_TYPE, str(path),
                                              quantization=PARAKEET_QUANTIZATION,
                                              providers=["CPUExecutionProvider"]))


def transcribe_parakeet(runner: ParakeetRunner, pcm: bytes) -> str:
    return runner.transcribe(pcm)


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


class ParakeetRunner:
    """onnx-asr's Parakeet decoding a take chunk by chunk (module docstring § chunks).

    ``transcribe`` is called with the whole take so far, by the service's single STT worker;
    each finished chunk's text is cached by the chunk's bytes (a few dozen entries), so a take
    that grows between passes re-decodes only its open tail.
    """

    CACHE_ENTRIES = 64

    def __init__(self, model: Any) -> None:
        self.model = model
        self._texts: OrderedDict[bytes, str] = OrderedDict()
        self._lock = threading.Lock()

    def transcribe(self, pcm: bytes) -> str:
        """16 kHz mono ``pcm_s16le`` -> text. TDT decodes greedily, so a partial and a final
        pass are the same computation."""
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
        text = str(self.model.recognize(samples.astype("float32") / 32768.0,
                                        sample_rate=_SAMPLE_RATE)).strip()
        if cached:  # the open tail changes on every pass: never worth a slot
            with self._lock:
                self._texts[key] = text
                while len(self._texts) > self.CACHE_ENTRIES:
                    self._texts.popitem(last=False)
        return text
