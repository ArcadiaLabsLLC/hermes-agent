"""Bundled Hermes's speech service: one STT model (Whisper or Parakeet TDT, both ONNX) and one voice.

Plan D3 items 1-2 (launcher ``docs/embedded_hermes/planned/``): the Launcher
downloads speech models into its models folder and samples the voice; bundled
Hermes LOADS the models from explicit local paths and runs inference, served as
``runtime.speech.*`` (:mod:`agent_runtime.serve_rpc.speech`). Contract:
``docs/agent-runtime-harness/runtime-speech-methods.md``.

Enable, never reimplement: both STT engines load through onnx-asr
(:mod:`agent_runtime.speech_stt_engines`) and the Whisper silence gate is
upstream's (``_upstream_doors.whisper_confident_text``). What this module adds is what upstream has no
equivalent for: path validation that answers ``unavailable`` with a typed reason
BEFORE any loader runs (so a missing or partial model can never fall through to
a download), streaming sessions over pushed PCM chunks, and admission of every
load through :mod:`agent_runtime.model_admission`.

No network: a model is only ever named by an absolute local path, an STT model
is a directory (onnx-asr given a model type and an existing directory never
resolves against a Hub) and a voice is an existing ``.onnx``. The bundled profile also sets
``HF_HUB_OFFLINE``, which upstream's Piper resolver now honours too.

Which STT engine runs a model is decided by the model folder's artifact set
(:func:`agent_runtime.speech_stt_engines.engine_for`), never by a config string.
"""

from __future__ import annotations

import base64
import binascii
import importlib.util
import json
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from agent_runtime import speech_stt_engines as stt_engines
from agent_runtime.model_admission import AdmissionRefused, ModelAdmission, admission
from agent_runtime.speech_stt_engines import nonempty as _nonempty

__layer__ = "stores"

__all__ = [
    "SPEECH_CONTRACT",
    "SpeechEngines",
    "SpeechRefused",
    "SpeechService",
    "inspect_stt",
    "inspect_tts",
    "service",
    "set_service",
]

SPEECH_CONTRACT = 1

#: Input audio: what the Launcher (the voice sampling authority) sends.
INPUT_SAMPLE_RATE = 16000
INPUT_ENCODING = "pcm_s16le"
_BYTES_PER_SECOND_IN = INPUT_SAMPLE_RATE * 2  # 32 KB/s — the wire budget the design assumed

#: One pushed chunk, decoded. 2 s of audio; the Launcher sends ~100-250 ms.
MAX_CHUNK_BYTES = 64 * 1024
#: One recognition stream. Dictation is short; this bounds the buffer at 3.84 MB.
MAX_STREAM_SECONDS = 120
#: Audio before the FIRST partial, and new audio between later ones. One Whisper CPU pass costs
#: about 0.5 s whatever the chunk length (Whisper pads to a 30 s window), so the first starts early.
FIRST_PARTIAL_MS = 300
PARTIAL_INTERVAL_MS = 600
#: How much trailing audio a partial transcribes is the engine's
#: (``speech_stt_engines.SttEngine.partial_window_seconds``).
#: Streams open at once, and how long an untouched one lives.
MAX_STREAMS = 4
STREAM_IDLE_SECONDS = 60.0

#: Synthesized audio is pushed in chunks of at most this many raw bytes (base64 adds a third).
OUT_CHUNK_BYTES = 32 * 1024
MAX_TEXT_CHARS = 4000

#: Estimated resident bytes per byte on disk, and fixed runtime overhead (measured on the CPU
#: path in the contract doc; an estimate, so it rounds up).
#: (Each STT engine carries its own figures: ``speech_stt_engines.STT_ENGINES``.)
_TTS_DISK_FACTOR = 1.5
_TTS_OVERHEAD = 64 * 1024 * 1024


STT_HOLDER = "speech:stt"
TTS_HOLDER = "speech:tts"


class SpeechRefused(Exception):
    """A request the service will not run. ``code`` is the family, ``reason`` the branch point."""

    def __init__(self, reason: str, code: str, message: str = "", **data: Any) -> None:
        super().__init__(message or reason)
        self.reason, self.code, self.data = reason, code, data


# ── model inspection (no loader, no network) ────────────────────────────────


def _unavailable(reason: str, path: Path | str | None, **extra: Any) -> dict:
    return {"state": "unavailable", "reason": reason, "model_path": None if path is None else str(path), **extra}


def _local_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip()).expanduser()
    return path if path.is_absolute() else None


def inspect_stt(path: Path | None, *, importable: Callable[[str], bool]) -> dict:
    """``available`` or ``unavailable`` + reason for an STT model DIRECTORY: a Whisper or a
    Parakeet TDT int8 ONNX export — the folder's files say which."""
    if path is None:
        return _unavailable("model_unset", None)
    if not path.is_dir():
        return _unavailable("model_missing", path)
    engine = stt_engines.engine_for(path)
    missing = stt_engines.missing_files(engine, path)
    if missing:
        return _unavailable("model_partial", path, missing=missing, engine=engine.name)
    model_type = stt_engines.unsupported_model_type(engine, path)
    if model_type is not None:
        return _unavailable("model_unsupported", path, engine=engine.name, model_type=model_type)
    if not importable(engine.name):
        return _unavailable("engine_missing", path, engine=engine.name)
    size = sum(f.stat().st_size for f in path.iterdir() if f.is_file())
    return {"state": "available", "reason": None, "model_path": str(path), "disk_bytes": size,
            "engine": engine.name}


def inspect_tts(path: Path | None, *, engine_ok: bool) -> dict:
    """``available`` or ``unavailable`` + reason for a voice on the pack's onnxruntime runner.

    A Piper voice is ``<voice>.onnx`` + ``.onnx.json``; Kokoro is its ``.onnx`` with
    ``voices-v1.0.bin`` beside it. Either needs its phonemizer artifact beside it
    (:data:`agent_runtime.speech_phonemize.PHONEMIZER_ARTIFACTS`) — checked here, before the
    loader, so a voice without one reads ``phonemizer_missing`` rather than failing to load.
    """
    if path is None:
        return _unavailable("model_unset", None)
    if path.suffix.lower() != ".onnx":
        return _unavailable("model_not_local", path)
    from agent_runtime.speech_onnx_voice import KOKORO_SAMPLE_RATE, KOKORO_VOICES, voice_family

    sidecar = path.with_name(path.name + ".json")
    family = voice_family(path)
    if family is None and not path.exists():
        return _unavailable("model_missing", path)
    companion = (path.parent / KOKORO_VOICES) if family == "kokoro" else sidecar
    missing = [p.name for p in (path, companion) if not _nonempty(p)]
    if missing:
        return _unavailable("model_partial", path, missing=missing)
    rate, phonemized = KOKORO_SAMPLE_RATE, True
    if family == "piper":
        try:
            config = json.loads(sidecar.read_text(encoding="utf-8"))
            rate, phonemized = config["audio"]["sample_rate"], config.get("phoneme_type", "espeak") == "espeak"
        except (OSError, ValueError, KeyError, TypeError):
            return _unavailable("model_partial", path, missing=[sidecar.name])
        if type(rate) is not int or rate <= 0:
            return _unavailable("model_partial", path, missing=[sidecar.name])
    if phonemized:
        from agent_runtime.speech_phonemize import artifact_files

        # A voice with no phonemizer cannot say anything: typed, before the loader.
        absent = [p.name for p in artifact_files(family, path) if not _nonempty(p)]
        if absent:
            return _unavailable("phonemizer_missing", path, missing=absent, voice_family=family)
    if not engine_ok:
        return _unavailable("engine_missing", path, engine="onnxruntime")
    return {"state": "available", "reason": None, "model_path": str(path), "voice_family": family,
            "disk_bytes": path.stat().st_size + companion.stat().st_size, "sample_rate": rate}


# ── engines (upstream's, behind one seam so tests can stand in) ────────────


class SpeechEngines:
    """The real engines. Tests pass a fake with the same five methods."""

    def stt_importable(self, engine: str = stt_engines.WHISPER) -> bool:
        return stt_engines.engine_importable(stt_engines.STT_ENGINES[engine])

    def tts_importable(self) -> bool:
        return all(importlib.util.find_spec(name) is not None for name in ("onnxruntime", "numpy"))

    def load_stt(self, path: Path, *, device: str, compute_type: str) -> Any:
        """The model in ``path`` on the engine its artifact set names (``engine_for``)."""
        engine = stt_engines.engine_for(path).name
        return _SttModel(engine, self._STT_LOADERS[engine](self, path, device, compute_type))

    def transcribe(self, model: Any, pcm: bytes, *, final: bool) -> str:
        # Both engines decode greedily through a chunked runner: a partial and a final agree.
        return model.model.transcribe(pcm)

    def _load_whisper(self, path: Path, device: str, compute_type: str) -> Any:
        from agent_runtime._upstream_doors import whisper_confident_text

        # Upstream's silence-hallucination gate, with the user's ``stt.local`` thresholds.
        local = _stt_config().get("local") or {}
        return stt_engines.load_whisper(
            path, keep=lambda segment: bool(whisper_confident_text([segment], local)))

    def _load_parakeet(self, path: Path, device: str, compute_type: str) -> Any:
        return stt_engines.load_parakeet(path)

    def load_tts(self, path: Path) -> Any:
        from agent_runtime.speech_onnx_voice import load_voice

        return load_voice(path)

    def unload_tts(self) -> None:
        pass  # the voice object is the whole model: dropping the slot's reference frees it

    def synthesize(self, voice: Any, text: str) -> Iterator[tuple[int, bytes]]:
        return voice.synthesize(text)

    #: STT engine name -> its loader (routing is data, not a ladder). Both load CPU int8, the
    #: only build this service loads.
    _STT_LOADERS = {stt_engines.WHISPER: _load_whisper, stt_engines.PARAKEET: _load_parakeet}


@dataclass(frozen=True)
class _SttModel:
    """A loaded STT model and the engine that decodes it."""

    engine: str
    model: Any


def _stt_config() -> dict:
    """The user's ``stt`` section, English unless it says otherwise (owner ruling 1: English first)."""
    try:
        from hermes_cli.config import load_config

        config = dict(load_config().get("stt") or {})
    except Exception:  # noqa: BLE001 - an unreadable config is upstream's defaults
        config = {}
    config.setdefault("language", "en")
    return config


def _configured_paths() -> tuple[Any, Any]:
    """``stt.local.model`` / ``tts.piper.voice`` from config — used only when they are absolute paths."""
    try:
        from hermes_cli.config import load_config

        config = load_config()
    except Exception:  # noqa: BLE001
        return None, None
    stt = ((config.get("stt") or {}).get("local") or {}).get("model")
    tts = ((config.get("tts") or {}).get("piper") or {}).get("voice")
    return stt, tts


# ── the service ─────────────────────────────────────────────────────────────


@dataclass
class _Slot:
    kind: str
    holder: str
    state: str = "unloaded"  # unloaded | loading | loaded
    path: Path | None = None
    model: Any = None
    reserved: int = 0
    error: dict | None = None
    unloaded_reason: str | None = None
    sample_rate: int | None = None
    engine: str | None = None


@dataclass
class _Stream:
    stream_id: str
    connection_key: str | None
    emit: Callable[[str, dict], bool] | None
    pcm: bytearray = field(default_factory=bytearray)
    next_seq: int = 0
    opened_at: float = 0.0
    touched_at: float = 0.0
    partial_at_bytes: int = 0
    partial_running: bool = False
    partial_future: Future | None = None
    partials: int = 0
    ended: bool = False


class SpeechService:
    def __init__(self, *, engines: Any = None, authority: ModelAdmission | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 configured: Callable[[], tuple[Any, Any]] = _configured_paths) -> None:
        self.engines = engines or SpeechEngines()
        self._authority = authority
        self._clock = clock
        self._configured = configured
        self._lock = threading.RLock()
        self.stt = _Slot("stt", STT_HOLDER)
        self.tts = _Slot("tts", TTS_HOLDER)
        self._streams: dict[str, _Stream] = {}
        self._synth_active = 0
        self._stt_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speech-stt")
        self._tts_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speech-tts")

    @property
    def authority(self) -> ModelAdmission:
        return self._authority if self._authority is not None else admission()

    # ── resolution + status ─────────────────────────────────────────────

    def _resolve(self, params: dict) -> tuple[Path | None, Path | None, dict]:
        """Absolute paths for the two models, from params, else from config. Nothing is fetched."""
        notes: dict = {}
        models_dir = params.get("models_dir")
        base = _local_path(models_dir) if models_dir is not None else None
        if models_dir is not None and base is None:
            raise SpeechRefused("models_dir_invalid", "invalid_params", "models_dir must be an absolute path")
        configured_stt, configured_tts = self._configured()

        def pick(name: str, value: Any, fallback: Any, suffix: str = "") -> Path | None:
            if value is None:
                value = fallback
                if value is None:
                    return None
            if not isinstance(value, str) or not value.strip() or "\0" in value:
                raise SpeechRefused(f"{name}_invalid", "invalid_params", f"{name} must be a non-empty string")
            path = _local_path(value)
            if path is not None:
                return path
            if base is not None and Path(value).name == value and value not in (".", ".."):
                return base / (value + suffix if suffix and not value.endswith(suffix) else value)
            notes[name] = "model_not_local"
            return None

        stt = pick("stt_model", params.get("stt_model"), configured_stt)
        tts = pick("tts_voice", params.get("tts_voice"), configured_tts, ".onnx")
        return stt, tts, notes

    def _inspect(self, slot: _Slot, path: Path | None, note: str | None) -> dict:
        if note:
            return _unavailable(note, None)
        if slot.kind == "stt":
            return inspect_stt(path, importable=self.engines.stt_importable)
        return inspect_tts(path, engine_ok=self.engines.tts_importable())

    def _slot_view(self, slot: _Slot, params: dict | None = None) -> dict:
        engine = slot.engine or (stt_engines.WHISPER if slot.kind == "stt" else "onnxruntime")
        if slot.state in ("loaded", "loading"):
            view = {"state": slot.state, "reason": None, "model_path": str(slot.path)}
        else:
            stt, tts, notes = self._resolve(params or {})
            path = stt if slot.kind == "stt" else tts
            view = self._inspect(slot, path, notes.get("stt_model" if slot.kind == "stt" else "tts_voice"))
            if slot.error is not None and view["state"] == "available":
                view.update(state="unavailable", reason=slot.error["reason"], error=slot.error)
        view.update(engine=view.get("engine") or engine, reserved_bytes=slot.reserved,
                    unloaded_reason=slot.unloaded_reason)
        if slot.kind == "stt":
            view.update(device="cpu", compute_type="int8", input_sample_rate=INPUT_SAMPLE_RATE,
                        input_encoding=INPUT_ENCODING)
        else:
            view.setdefault("sample_rate", slot.sample_rate)
        return view

    def status(self, params: dict | None = None) -> dict:
        with self._lock:
            return {"contract": SPEECH_CONTRACT, "stt": self._slot_view(self.stt, params),
                    "tts": self._slot_view(self.tts, params), "streams": len(self._streams),
                    "admission": self.authority.status()}

    # ── load / unload ───────────────────────────────────────────────────

    def load(self, params: dict) -> dict:
        which = params.get("which", "both")
        if which not in ("stt", "tts", "both"):
            raise SpeechRefused("which_invalid", "invalid_params", "which must be stt, tts or both")
        stt_path, tts_path, notes = self._resolve(params)
        results = {}
        for slot, path, note_key in ((self.stt, stt_path, "stt_model"), (self.tts, tts_path, "tts_voice")):
            if which in (slot.kind, "both"):
                results[slot.kind] = self._load_slot(slot, path, notes.get(note_key))
        return {"contract": SPEECH_CONTRACT, "results": results, **self.status(params)}

    def _load_slot(self, slot: _Slot, path: Path | None, note: str | None) -> dict:
        with self._lock:
            if slot.state == "loading":
                return {"state": "loading", "reason": "load_in_progress"}
            already_loaded = slot.state == "loaded"
            if already_loaded and slot.path == path:
                return {"state": "loaded", "reason": None}
            view = self._inspect(slot, path, note)
            if view["state"] != "available":
                return {"state": "unavailable", "reason": view["reason"], **{k: v for k, v in view.items()
                                                                          if k in ("missing", "engine", "model_type", "voice_family")}}
            if already_loaded:
                self._drop(slot, "replaced")
            slot.state, slot.path, slot.error, slot.engine = "loading", path, None, view.get("engine")
        estimate = self._estimate(slot.kind, view["disk_bytes"], view.get("engine"))
        try:
            self.authority.reserve(slot.holder, kind=slot.kind, resource="ram", bytes=estimate,
                                   evict=lambda s=slot: self._evict(s))
        except AdmissionRefused as refusal:
            with self._lock:
                slot.state, slot.path = "unloaded", None
            return {"state": "refused", "reason": refusal.reason, **refusal.details}
        try:
            if slot.kind == "stt":
                model = self.engines.load_stt(path, device="cpu", compute_type="int8")
            else:
                model = self.engines.load_tts(path)
        except Exception as exc:  # noqa: BLE001 - a load failure is a typed state, never a raise
            self.authority.release(slot.holder)
            with self._lock:
                slot.state, slot.path, slot.model, slot.reserved = "unloaded", None, None, 0
                slot.error = {"reason": "load_failed", "error_class": type(exc).__name__}
            return {"state": "unavailable", "reason": "load_failed", "error_class": type(exc).__name__}
        with self._lock:
            slot.model, slot.state, slot.reserved, slot.unloaded_reason = model, "loaded", estimate, None
            slot.sample_rate = view.get("sample_rate")
            self._mark_idle(slot)
        return {"state": "loaded", "reason": None, "reserved_bytes": estimate}

    @staticmethod
    def _estimate(kind: str, disk_bytes: int, engine: str | None = None) -> int:
        if kind == "stt":
            figures = stt_engines.STT_ENGINES[engine or stt_engines.WHISPER]
            return int(disk_bytes * figures.disk_factor) + figures.overhead_bytes
        return int(disk_bytes * _TTS_DISK_FACTOR) + _TTS_OVERHEAD

    def _busy(self, slot: _Slot) -> bool:
        return bool(self._streams) if slot.kind == "stt" else self._synth_active > 0

    def _mark_idle(self, slot: _Slot) -> None:
        if slot.state == "loaded":
            self.authority.mark(slot.holder, idle=not self._busy(slot))

    def _drop(self, slot: _Slot, reason: str) -> None:
        if slot.kind == "tts" and slot.model is not None:
            try:
                self.engines.unload_tts()
            except Exception:  # noqa: BLE001 - the reference is dropped either way
                pass
        slot.model, slot.state, slot.path, slot.reserved = None, "unloaded", None, 0
        slot.unloaded_reason = reason
        self.authority.release(slot.holder)

    def _evict(self, slot: _Slot) -> None:
        """The admission authority's evictor: unload an IDLE model, refuse a busy one."""
        with self._lock:
            if self._busy(slot):
                raise RuntimeError(f"speech {slot.kind} model is in use")
            if slot.state == "loaded":
                self._drop(slot, "evicted")

    def unload(self, params: dict) -> dict:
        which = params.get("which", "both")
        if which not in ("stt", "tts", "both"):
            raise SpeechRefused("which_invalid", "invalid_params", "which must be stt, tts or both")
        with self._lock:
            for slot in (self.stt, self.tts):
                if which in (slot.kind, "both"):
                    self._unload_slot(slot)
            return self.status()

    def _unload_slot(self, slot: _Slot) -> None:
        """Unload one model (caller holds the lock); unloading STT ends every open recognition stream."""
        if slot.kind == "stt":
            for stream in self._streams.values():
                stream.ended = True
            self._streams.clear()
        if slot.state == "loaded":
            self._drop(slot, "unloaded")
        slot.error = None

    # ── recognition ─────────────────────────────────────────────────────

    def _sweep(self, now: float) -> None:
        for stream_id in [s for s, st in self._streams.items() if now - st.touched_at > STREAM_IDLE_SECONDS]:
            self._streams.pop(stream_id).ended = True

    def recognize_begin(self, params: dict, *, connection_key: str | None,
                        emit: Callable[[str, dict], bool] | None) -> dict:
        rate = params.get("sample_rate", INPUT_SAMPLE_RATE)
        encoding = params.get("encoding", INPUT_ENCODING)
        if rate != INPUT_SAMPLE_RATE or encoding != INPUT_ENCODING:
            raise SpeechRefused("audio_format_unsupported", "invalid_params",
                                f"send {INPUT_ENCODING} mono at {INPUT_SAMPLE_RATE} Hz",
                                sample_rate=INPUT_SAMPLE_RATE, encoding=INPUT_ENCODING)
        language = params.get("language", "en")
        if language != "en":
            raise SpeechRefused("language_unsupported", "invalid_params", "English only", languages=["en"])
        with self._lock:
            if self.stt.state != "loaded":
                raise SpeechRefused("model_not_loaded", "conflict", "load the speech-to-text model first",
                                    model="stt")
            now = self._clock()
            self._sweep(now)
            if len(self._streams) >= MAX_STREAMS:
                raise SpeechRefused("too_many_streams", "conflict", limit=MAX_STREAMS)
            stream = _Stream(stream_id=str(uuid.uuid4()), connection_key=connection_key, emit=emit,
                             opened_at=now, touched_at=now)
            self._streams[stream.stream_id] = stream
            self._mark_idle(self.stt)
            return {"contract": SPEECH_CONTRACT, "stream_id": stream.stream_id, "partials": emit is not None,
                    "sample_rate": INPUT_SAMPLE_RATE, "encoding": INPUT_ENCODING,
                    "max_chunk_bytes": MAX_CHUNK_BYTES, "max_seconds": MAX_STREAM_SECONDS}

    def _stream(self, stream_id: Any, connection_key: str | None) -> _Stream:
        stream = self._streams.get(stream_id) if isinstance(stream_id, str) else None
        if stream is None or stream.connection_key != connection_key:
            raise SpeechRefused("stream_not_found", "not_found", stream_id=stream_id if isinstance(stream_id, str) else None)
        return stream

    def recognize_push(self, params: dict, *, connection_key: str | None) -> dict:
        audio = params.get("audio")
        if not isinstance(audio, str) or len(audio) > (MAX_CHUNK_BYTES * 4) // 3 + 4:
            raise SpeechRefused("audio_invalid", "invalid_params", "audio must be base64 PCM, at most "
                                f"{MAX_CHUNK_BYTES} bytes decoded")
        try:
            pcm = base64.b64decode(audio, validate=True)
        except (binascii.Error, ValueError):
            raise SpeechRefused("audio_invalid", "invalid_params", "audio is not valid base64") from None
        if len(pcm) % 2 or len(pcm) > MAX_CHUNK_BYTES:
            raise SpeechRefused("audio_invalid", "invalid_params", "audio must be whole 16-bit samples")
        with self._lock:
            stream = self._stream(params.get("stream_id"), connection_key)
            seq = params.get("seq")
            if type(seq) is not int or seq != stream.next_seq:
                raise SpeechRefused("seq_gap", "conflict", expected=stream.next_seq)
            if len(stream.pcm) + len(pcm) > MAX_STREAM_SECONDS * _BYTES_PER_SECOND_IN:
                raise SpeechRefused("stream_too_long", "conflict", max_seconds=MAX_STREAM_SECONDS)
            stream.pcm.extend(pcm)
            stream.next_seq += 1
            stream.touched_at = self._clock()
            fresh = len(stream.pcm) - stream.partial_at_bytes
            interval = FIRST_PARTIAL_MS if stream.partial_at_bytes == 0 else PARTIAL_INTERVAL_MS
            if (stream.emit is not None and not stream.partial_running
                    and fresh * 1000 >= interval * _BYTES_PER_SECOND_IN):
                stream.partial_running = True
                stream.partial_at_bytes = len(stream.pcm)
                seconds = stt_engines.STT_ENGINES[self.stt.engine or stt_engines.WHISPER].partial_window_seconds
                whole = seconds is None or len(stream.pcm) <= seconds * _BYTES_PER_SECOND_IN
                window = bytes(stream.pcm) if whole else bytes(stream.pcm[-seconds * _BYTES_PER_SECOND_IN:])
                stream.partial_future = self._stt_pool.submit(self._partial, stream, window, len(stream.pcm), whole)
            return {"contract": SPEECH_CONTRACT, "stream_id": stream.stream_id, "seq": seq,
                    "audio_ms": _ms(len(stream.pcm))}

    def _partial(self, stream: _Stream, pcm: bytes, total: int, whole: bool) -> tuple[int, str] | None:
        """One preview pass. Returns ``(bytes covered, text)`` when it covered the WHOLE take so far,
        which the final adopts when no audio arrived after it (see :meth:`recognize_end`)."""
        try:
            if stream.ended and not whole:
                return None
            with self._lock:
                model = self.stt.model
            if model is None:
                return None
            text = self.engines.transcribe(model, pcm, final=False)
            stream.partials += 1
            stream.emit("runtime.speech.recognize.partial",
                        {"stream_id": stream.stream_id, "index": stream.partials, "text": text,
                         "audio_ms": _ms(total)})
            return (total, text) if whole else None
        except Exception:  # noqa: BLE001 - a partial is a preview; the final is the answer
            return None
        finally:
            stream.partial_running = False

    def recognize_end(self, params: dict, *, connection_key: str | None) -> Future:
        """Close the stream and return a Future for the final result (also pushed as an event)."""
        with self._lock:
            stream = self._stream(params.get("stream_id"), connection_key)
            stream.ended = True
            self._streams.pop(stream.stream_id, None)
            model = self.stt.model
            ended_at = time.perf_counter()
            pcm = bytes(stream.pcm)
            pending = stream.partial_future if stream.partial_running else None
        return self._stt_pool.submit(self._final, stream, model, pcm, ended_at, pending)

    def _final(self, stream: _Stream, model: Any, pcm: bytes, ended_at: float,
               pending: Future | None) -> dict:
        try:
            if model is None:
                raise SpeechRefused("model_not_loaded", "conflict", model="stt")
            # The pool is single-threaded, so ``pending`` (queued before this) is already done.
            covered = pending.result() if pending is not None and pending.done() else None
            if covered is not None and covered[0] == len(pcm):
                text, adopted = covered[1], True  # no audio after that pass: a second one adds nothing
            else:
                text, adopted = (self.engines.transcribe(model, pcm, final=True) if pcm else ""), False
            result = {"contract": SPEECH_CONTRACT, "stream_id": stream.stream_id, "text": text,
                      "audio_ms": _ms(len(pcm)), "partials": stream.partials, "adopted_partial": adopted,
                      "final_latency_ms": int((time.perf_counter() - ended_at) * 1000)}
            if stream.emit is not None:
                stream.emit("runtime.speech.recognize.final", {k: v for k, v in result.items() if k != "contract"})
            return result
        finally:
            with self._lock:
                self._mark_idle(self.stt)

    def recognize_cancel(self, params: dict, *, connection_key: str | None) -> dict:
        with self._lock:
            stream = self._stream(params.get("stream_id"), connection_key)
            stream.ended = True
            self._streams.pop(stream.stream_id, None)
            self._mark_idle(self.stt)
            return {"contract": SPEECH_CONTRACT, "stream_id": stream.stream_id, "cancelled": True}

    # ── synthesis ───────────────────────────────────────────────────────

    def synthesize(self, params: dict, *, emit: Callable[[str, dict], bool]) -> Future:
        text = params.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise SpeechRefused("text_invalid", "invalid_params", f"text must be 1-{MAX_TEXT_CHARS} characters")
        with self._lock:
            if self.tts.state != "loaded":
                raise SpeechRefused("model_not_loaded", "conflict", "load the text-to-speech voice first",
                                    model="tts")
            voice = self.tts.model
            self._synth_active += 1
            self._mark_idle(self.tts)
        return self._tts_pool.submit(self._synthesize, voice, text, emit)

    def _synthesize(self, voice: Any, text: str, emit: Callable[[str, dict], bool]) -> dict:
        synth_id, started = str(uuid.uuid4()), time.perf_counter()
        seq, total, rate, first_ms = 0, 0, None, None
        try:
            for sample_rate, pcm in self.engines.synthesize(voice, text):
                rate = rate or sample_rate
                for offset in range(0, len(pcm), OUT_CHUNK_BYTES):
                    piece = pcm[offset:offset + OUT_CHUNK_BYTES]
                    if first_ms is None:
                        first_ms = int((time.perf_counter() - started) * 1000)
                    emit("runtime.speech.synthesize.chunk",
                         {"synth_id": synth_id, "seq": seq, "sample_rate": sample_rate,
                          "audio": base64.b64encode(piece).decode("ascii")})
                    seq += 1
                    total += len(piece)
            return {"contract": SPEECH_CONTRACT, "synth_id": synth_id, "sample_rate": rate, "channels": 1,
                    "encoding": INPUT_ENCODING, "chunks": seq, "bytes": total,
                    "audio_ms": int(total * 1000 / (2 * rate)) if rate else 0,
                    "first_chunk_ms": first_ms, "elapsed_ms": int((time.perf_counter() - started) * 1000)}
        finally:
            with self._lock:
                self._synth_active -= 1
                self._mark_idle(self.tts)

    def close(self) -> None:
        with self._lock:
            self._streams.clear()
            for slot in (self.stt, self.tts):
                if slot.state == "loaded":
                    self._drop(slot, "closed")
        self._stt_pool.shutdown(wait=False, cancel_futures=True)
        self._tts_pool.shutdown(wait=False, cancel_futures=True)


def _ms(pcm_bytes: int) -> int:
    return pcm_bytes * 1000 // _BYTES_PER_SECOND_IN


_lock = threading.Lock()
_service: SpeechService | None = None


def service() -> SpeechService:
    global _service
    with _lock:
        if _service is None:
            _service = SpeechService()
        return _service


def set_service(value: SpeechService | None) -> None:
    global _service
    with _lock:
        previous, _service = _service, value
    if previous is not None and previous is not value:
        previous.close()
