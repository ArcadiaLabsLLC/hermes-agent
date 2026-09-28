"""Bundled Hermes's speech service: one faster-whisper STT model and one Piper voice.

Plan D3 items 1-2 (launcher ``docs/embedded_hermes/planned/``): the Launcher
downloads speech models into its models folder and samples the voice; bundled
Hermes LOADS the models from explicit local paths and runs inference, served as
``runtime.speech.*`` (:mod:`agent_runtime.serve_rpc.speech`). Contract:
``docs/agent-runtime-harness/runtime-speech-methods.md``.

Enable, never reimplement: loading goes through upstream's own loaders
(``_upstream_doors.whisper_load_model`` / ``piper_voice_for_config``), the
transcribe kwargs are upstream's ``build_local_transcribe_kwargs`` and the
silence gate is upstream's. What this module adds is what upstream has no
equivalent for: path validation that answers ``unavailable`` with a typed reason
BEFORE any loader runs (so a missing or partial model can never fall through to
a download), streaming sessions over pushed PCM chunks, and admission of every
load through :mod:`agent_runtime.model_admission`.

No network: a model is only ever named by an absolute local path, a whisper
model is a directory (faster-whisper never resolves a directory against the
Hub) and a Piper voice is an existing ``.onnx`` (upstream's resolver returns an
existing path before its download branch). The bundled profile also sets
``HF_HUB_OFFLINE``, which upstream's Piper resolver now honours too.
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

from agent_runtime.model_admission import AdmissionRefused, ModelAdmission, admission

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
#: Audio before the FIRST partial, and new audio between later ones. One CPU pass costs about
#: 0.7 s whatever the clip length (whisper pads to a 30 s window), so the first pass starts early.
FIRST_PARTIAL_MS = 300
PARTIAL_INTERVAL_MS = 600
#: A partial transcribes at most this much trailing audio, so its cost stays flat on long takes.
PARTIAL_WINDOW_SECONDS = 30
#: Streams open at once, and how long an untouched one lives.
MAX_STREAMS = 4
STREAM_IDLE_SECONDS = 60.0

#: Synthesized audio is pushed in chunks of at most this many raw bytes (base64 adds a third).
OUT_CHUNK_BYTES = 32 * 1024
MAX_TEXT_CHARS = 4000

#: Estimated resident bytes per byte on disk, and fixed runtime overhead (measured on the CPU
#: path in the contract doc; an estimate, so it rounds up).
_STT_DISK_FACTOR = 1.0
_STT_OVERHEAD = 96 * 1024 * 1024
_TTS_DISK_FACTOR = 1.5
_TTS_OVERHEAD = 64 * 1024 * 1024

_WHISPER_REQUIRED = ("model.bin", "config.json", "tokenizer.json")
_WHISPER_VOCABULARY = ("vocabulary.txt", "vocabulary.json")

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


def inspect_stt(path: Path | None, *, engine_ok: bool) -> dict:
    """``available`` or ``unavailable`` + reason for a faster-whisper (CTranslate2) model DIRECTORY."""
    if path is None:
        return _unavailable("model_unset", None)
    if not path.is_dir():
        return _unavailable("model_missing", path)
    missing = [name for name in _WHISPER_REQUIRED if not _nonempty(path / name)]
    if not any(_nonempty(path / name) for name in _WHISPER_VOCABULARY):
        missing.append(_WHISPER_VOCABULARY[0])
    if missing:
        return _unavailable("model_partial", path, missing=missing)
    try:
        json.loads((path / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _unavailable("model_partial", path, missing=["config.json"])
    if not engine_ok:
        return _unavailable("engine_missing", path, engine="faster-whisper")
    size = sum(f.stat().st_size for f in path.iterdir() if f.is_file())
    return {"state": "available", "reason": None, "model_path": str(path), "disk_bytes": size}


def inspect_tts(path: Path | None, *, engine_ok: bool) -> dict:
    """``available`` or ``unavailable`` + reason for a Piper voice (``<voice>.onnx`` + ``.onnx.json``)."""
    if path is None:
        return _unavailable("model_unset", None)
    if path.suffix.lower() != ".onnx":
        return _unavailable("model_not_local", path)
    sidecar = path.with_name(path.name + ".json")
    if not path.exists() and not sidecar.exists():
        return _unavailable("model_missing", path)
    missing = [p.name for p in (path, sidecar) if not _nonempty(p)]
    if missing:
        return _unavailable("model_partial", path, missing=missing)
    try:
        rate = json.loads(sidecar.read_text(encoding="utf-8"))["audio"]["sample_rate"]
    except (OSError, ValueError, KeyError, TypeError):
        return _unavailable("model_partial", path, missing=[sidecar.name])
    if type(rate) is not int or rate <= 0:
        return _unavailable("model_partial", path, missing=[sidecar.name])
    if not engine_ok:
        return _unavailable("engine_missing", path, engine="piper")
    return {"state": "available", "reason": None, "model_path": str(path),
            "disk_bytes": path.stat().st_size + sidecar.stat().st_size, "sample_rate": rate}


def _nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


# ── engines (upstream's, behind one seam so tests can stand in) ────────────


class SpeechEngines:
    """The real engines. Tests pass a fake with the same five methods."""

    def stt_importable(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def tts_importable(self) -> bool:
        from agent_runtime._upstream_doors import piper_engine_importable

        return piper_engine_importable()

    def load_stt(self, path: Path, *, device: str, compute_type: str) -> Any:
        from agent_runtime._upstream_doors import whisper_load_model

        return whisper_load_model(str(path), device=device, compute_type=compute_type)

    def transcribe(self, model: Any, pcm: bytes, *, final: bool) -> str:
        import numpy as np

        from agent_runtime._upstream_doors import whisper_confident_text
        from tools.transcription_local import build_local_transcribe_kwargs

        config = _stt_config()
        kwargs = build_local_transcribe_kwargs(config)
        if not final:
            # A partial is a preview the final replaces: greedy decode keeps it inside the
            # first-words budget; the final keeps upstream's beam.
            kwargs["beam_size"] = 1
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(audio, **kwargs)
        return whisper_confident_text(segments, config.get("local") or {})

    def load_tts(self, path: Path) -> Any:
        from agent_runtime._upstream_doors import piper_voice_for_config

        voice, _config = piper_voice_for_config(
            {"piper": {"voice": str(path), "voices_dir": str(path.parent), "use_cuda": False}})
        return voice

    def unload_tts(self) -> None:
        from tools.tts_tool_lifecycle import release_tts_provider

        release_tts_provider("piper")

    def synthesize(self, voice: Any, text: str) -> Iterator[tuple[int, bytes]]:
        for chunk in voice.synthesize(text):
            yield chunk.sample_rate, chunk.audio_int16_bytes


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
            return inspect_stt(path, engine_ok=self.engines.stt_importable())
        return inspect_tts(path, engine_ok=self.engines.tts_importable())

    def _slot_view(self, slot: _Slot, params: dict | None = None) -> dict:
        engine = "faster-whisper" if slot.kind == "stt" else "piper"
        if slot.state in ("loaded", "loading"):
            view = {"state": slot.state, "reason": None, "model_path": str(slot.path)}
        else:
            stt, tts, notes = self._resolve(params or {})
            path = stt if slot.kind == "stt" else tts
            view = self._inspect(slot, path, notes.get("stt_model" if slot.kind == "stt" else "tts_voice"))
            if slot.error is not None and view["state"] == "available":
                view.update(state="unavailable", reason=slot.error["reason"], error=slot.error)
        view.update(engine=engine, reserved_bytes=slot.reserved, unloaded_reason=slot.unloaded_reason)
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
                                                                          if k in ("missing", "engine")}}
            if already_loaded:
                self._drop(slot, "replaced")
            slot.state, slot.path, slot.error = "loading", path, None
        estimate = self._estimate(slot.kind, view["disk_bytes"])
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
    def _estimate(kind: str, disk_bytes: int) -> int:
        if kind == "stt":
            return int(disk_bytes * _STT_DISK_FACTOR) + _STT_OVERHEAD
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
                    if slot.kind == "stt":
                        for stream in self._streams.values():
                            stream.ended = True
                        self._streams.clear()
                    if slot.state == "loaded":
                        self._drop(slot, "unloaded")
                    slot.error = None
            return self.status()

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
                whole = len(stream.pcm) <= PARTIAL_WINDOW_SECONDS * _BYTES_PER_SECOND_IN
                window = bytes(stream.pcm[-PARTIAL_WINDOW_SECONDS * _BYTES_PER_SECOND_IN:])
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
