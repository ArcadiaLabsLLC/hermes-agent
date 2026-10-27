"""The local-inference service: params, the model and label caches, scoring, the vector codec.

``embed_texts`` answers ``runtime.embed.texts`` and ``tag_image`` answers ``runtime.vision.tag``.
The model seam is ``loader(spec, folder)``: it answers a runner with ``embed(texts)`` (embedders)
or ``text_embeds(texts)`` / ``image_embeds(image)`` (CLIP), each returning unit-length rows.
The production loader is :func:`agent_runtime.local_inference.runners.load_runner`; tests pass a fake.

Admission: every load reserves its estimate (:func:`_estimate_bytes`) in the process's one model
budget (:mod:`agent_runtime.model_admission`) under the spec's ``kind`` (``embed`` / ``vision``)
before it touches memory, and releases it when the runner is dropped. An idle runner is evictable:
another model's reservation may unload it; a runner mid-call refuses. A reservation that does not
fit is the ``over_budget`` refusal (code ``conflict``).

Caches: at most :data:`MAX_LOADED` runners stay loaded, least recently used dropped first, and the
text-side label embeddings are kept per (model, folder, vocabulary hash) for the last
:data:`MAX_VOCABULARIES` vocabularies, so a composer re-asking with the same labels embeds only the
image.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import math
import struct
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterator

from agent_runtime.local_inference.models import (
    EMBED_MODELS,
    VISION_MODELS,
    LocalInferenceRefused,
    LocalModelSpec,
    absent_engine_modules,
    model_folder,
)
from agent_runtime.model_admission import AdmissionRefused, ModelAdmission, admission
from agent_runtime.process_state import register_process_state

__layer__ = "lanes"

__all__ = [
    "LOCAL_INFERENCE_CONTRACT",
    "MAX_IMAGE_BYTES",
    "MAX_LABELS",
    "MAX_TEXTS",
    "LocalInferenceService",
    "decode_vector",
    "encode_vector",
    "service",
    "set_service",
]

LOCAL_INFERENCE_CONTRACT = 1
MAX_TEXTS = 64
MAX_TEXT_CHARS = 16_000
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_LABELS = 512
MAX_LABEL_CHARS = 64
MAX_LOADED = 2
MAX_VOCABULARIES = 8
#: The zero-shot prompt CLIP's own evaluation uses; part of the vocabulary hash.
LABEL_PROMPT = "a photo of {label}."
#: CLIP's learned ``logit_scale`` (exp 4.6052 = 100) for openai/clip-vit-base-patch32.
CLIP_LOGIT_SCALE = 100.0
#: Admission estimate: resident bytes per byte of model files on disk, plus one onnxruntime
#: session's fixed overhead. An estimate, so it rounds up (int8 weights plus the CPU arena).
_DISK_FACTOR = 2.0
_SESSION_OVERHEAD = 64 * 1024 * 1024
#: Every reservation this service holds is named ``local_inference:<model>:<folder digest>``.
HOLDER_PREFIX = "local_inference:"


def encode_vector(vector: list[float]) -> str:
    """Little-endian float32, base64."""
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


def decode_vector(text: str) -> list[float]:
    raw = base64.b64decode(text)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def _texts(params: dict) -> list[str]:
    texts = params.get("texts")
    if not isinstance(texts, list) or not texts:
        raise LocalInferenceRefused("texts_empty", message="texts must be a non-empty list")
    if len(texts) > MAX_TEXTS:
        raise LocalInferenceRefused("texts_too_many", message=f"at most {MAX_TEXTS} texts per call")
    for text in texts:
        if not isinstance(text, str) or "\0" in text:
            raise LocalInferenceRefused("text_invalid", message="each text is a string")
        if len(text) > MAX_TEXT_CHARS:
            raise LocalInferenceRefused("text_too_long", message=f"each text is at most {MAX_TEXT_CHARS} characters")
    return list(texts)


def _labels(params: dict) -> list[str]:
    labels = params.get("labels")
    if not isinstance(labels, list) or not labels:
        raise LocalInferenceRefused("labels_empty", message="labels must be a non-empty list")
    if len(labels) > MAX_LABELS:
        raise LocalInferenceRefused("labels_too_many", message=f"at most {MAX_LABELS} labels per call")
    for label in labels:
        if not isinstance(label, str) or not label.strip() or not label.isprintable():
            raise LocalInferenceRefused("label_invalid", message="each label is a non-empty printable string")
        if len(label) > MAX_LABEL_CHARS:
            raise LocalInferenceRefused("label_too_long", message=f"each label is at most {MAX_LABEL_CHARS} characters")
    if len(set(labels)) != len(labels):
        raise LocalInferenceRefused("labels_duplicate", message="labels must be distinct")
    return list(labels)


def _top_k(params: dict, count: int) -> int:
    top_k = params.get("top_k", min(5, count))
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= count:
        raise LocalInferenceRefused("top_k_invalid", message=f"top_k must be an integer 1..{count}")
    return top_k


def _image(params: dict) -> bytes:
    value = params.get("image")
    if not isinstance(value, str) or not value:
        raise LocalInferenceRefused("image_invalid", message="image is a base64 string")
    if len(value) > (MAX_IMAGE_BYTES * 4) // 3 + 4:
        raise LocalInferenceRefused("image_too_large", message=f"image is at most {MAX_IMAGE_BYTES} bytes")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise LocalInferenceRefused("image_invalid", message="image is not valid base64") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise LocalInferenceRefused("image_too_large", message=f"image is at most {MAX_IMAGE_BYTES} bytes")
    _check_decodable(data)
    return data


def _check_decodable(data: bytes) -> None:
    """Pillow can read the header and the picture is not a decompression bomb."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as opened:
            width, height = opened.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise LocalInferenceRefused("image_unreadable", message="image is not a picture Pillow can read") from None
    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
        raise LocalInferenceRefused("image_too_large", message=f"image is over {MAX_IMAGE_PIXELS} pixels")


def _softmax(logits: list[float]) -> list[float]:
    peak = max(logits)
    weights = [math.exp(value - peak) for value in logits]
    total = sum(weights)
    return [weight / total for weight in weights]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _vocabulary_hash(labels: list[str]) -> str:
    return hashlib.sha256("\n".join([LABEL_PROMPT, *labels]).encode("utf-8")).hexdigest()


def _holder(spec: LocalModelSpec, folder: Path) -> str:
    return f"{HOLDER_PREFIX}{spec.model}:{hashlib.sha256(str(folder).encode('utf-8')).hexdigest()[:12]}"


def _estimate_bytes(spec: LocalModelSpec, folder: Path) -> int:
    disk = sum((folder / name).stat().st_size for name in spec.files)
    return int(disk * _DISK_FACTOR) + _SESSION_OVERHEAD


def _checked_rows(rows: Any, count: int, dim: int) -> list[list[float]]:
    rows = [list(row) for row in rows]
    if len(rows) != count or any(len(row) != dim for row in rows):
        raise RuntimeError(f"runner answered {len(rows)} rows, expected {count} of width {dim}")
    return rows


@dataclass
class _Loaded:
    runner: Any
    holder: str
    #: Calls holding this runner right now; a runner in use refuses eviction.
    users: int = 0


class LocalInferenceService:
    def __init__(self, *, loader: Callable[[LocalModelSpec, Path], Any] | None = None,
                 absent_modules: Callable[[], list[str]] = absent_engine_modules,
                 authority: ModelAdmission | None = None) -> None:
        self._loader = loader
        self._absent_modules = absent_modules
        self._authority = authority
        self._lock = threading.Lock()
        self._loaded: OrderedDict[tuple[str, str], _Loaded] = OrderedDict()
        self._vocabularies: OrderedDict[tuple[str, str, str], list[list[float]]] = OrderedDict()
        self._run_lock = threading.Lock()

    @property
    def authority(self) -> ModelAdmission:
        return self._authority if self._authority is not None else admission()

    @contextmanager
    def _runner(self, spec: LocalModelSpec, folder: Path) -> Iterator[Any]:
        """A loaded runner held in use (not evictable) for the width of the block."""
        key = (spec.model, str(folder))
        entry = self._load(spec, folder, key)
        try:
            yield entry.runner
        finally:
            with self._lock:
                entry.users -= 1
                if entry.users == 0 and self._loaded.get(key) is entry:
                    self.authority.mark(entry.holder, idle=True)

    def _use(self, entry: _Loaded) -> _Loaded:
        """Under ``_lock``: one more call holds ``entry``."""
        entry.users += 1
        if entry.users == 1:
            self.authority.mark(entry.holder, idle=False)
        return entry

    def _load(self, spec: LocalModelSpec, folder: Path, key: tuple[str, str]) -> _Loaded:
        absent = self._absent_modules()
        if absent:
            raise LocalInferenceRefused("engine_missing", "not_found",
                                        "the speech pack's onnxruntime is not installed", modules=absent)
        with self._lock:
            entry = self._loaded.get(key)
            if entry is not None:
                self._loaded.move_to_end(key)
                return self._use(entry)
        holder = _holder(spec, folder)
        try:
            self.authority.reserve(holder, kind=spec.kind, resource="ram", bytes=_estimate_bytes(spec, folder),
                                   evict=partial(self._evict, key))
        except AdmissionRefused as refusal:
            code = "conflict" if refusal.reason == "over_budget" else "handler_failed"
            raise LocalInferenceRefused(refusal.reason, code, f"{spec.model} was not admitted: {refusal}",
                                        **refusal.details) from refusal
        loader = self._loader
        if loader is None:
            from agent_runtime.local_inference.runners import load_runner as loader
        try:
            runner = loader(spec, folder)
        except Exception as exc:  # a load failure is a typed refusal, the class name only
            self.authority.release(holder)
            raise LocalInferenceRefused("load_failed", "handler_failed", f"{spec.model} failed to load",
                                        error_class=type(exc).__name__) from exc
        with self._lock:
            entry = self._loaded[key] = _Loaded(runner, holder)
            self._loaded.move_to_end(key)
            self._use(entry)
            self._trim()
        return entry

    def _trim(self) -> None:
        """Under ``_lock``: drop least-recently-used idle runners past :data:`MAX_LOADED`."""
        idle = [key for key, entry in self._loaded.items() if entry.users == 0]
        while len(self._loaded) > MAX_LOADED and idle:
            dropped = self._loaded.pop(idle.pop(0))
            self.authority.release(dropped.holder)

    def _evict(self, key: tuple[str, str]) -> None:
        """The admission authority's evictor: unload an IDLE runner, refuse one in use."""
        with self._lock:
            entry = self._loaded.get(key)
            if entry is not None and entry.users:
                raise RuntimeError(f"local inference model {key[0]} is in use")
            self._loaded.pop(key, None)

    def embed_texts(self, params: Any) -> dict:
        params = params if isinstance(params, dict) else {}
        spec, folder = model_folder(params, EMBED_MODELS)
        texts = _texts(params)
        with self._runner(spec, folder) as runner, self._run_lock:
            rows = _checked_rows(runner.embed(texts), len(texts), spec.dim)
        return {"contract": LOCAL_INFERENCE_CONTRACT, "model": spec.model, "dim": spec.dim,
                "encoding": "f32le_base64", "vectors": [encode_vector(row) for row in rows]}

    def _label_rows(self, spec: LocalModelSpec, folder: Path, runner: Any, labels: list[str]) -> list[list[float]]:
        key = (spec.model, str(folder), _vocabulary_hash(labels))
        with self._lock:
            rows = self._vocabularies.get(key)
            if rows is not None:
                self._vocabularies.move_to_end(key)
                return rows
        prompts = [LABEL_PROMPT.format(label=label) for label in labels]
        rows = _checked_rows(runner.text_embeds(prompts), len(labels), spec.dim)
        with self._lock:
            self._vocabularies[key] = rows
            while len(self._vocabularies) > MAX_VOCABULARIES:
                self._vocabularies.popitem(last=False)
        return rows

    def tag_image(self, params: Any) -> dict:
        params = params if isinstance(params, dict) else {}
        spec, folder = model_folder(params, VISION_MODELS)
        labels = _labels(params)
        top_k = _top_k(params, len(labels))
        image = _image(params)
        with self._runner(spec, folder) as runner, self._run_lock:
            label_rows = self._label_rows(spec, folder, runner, labels)
            image_row = _checked_rows([runner.image_embeds(image)], 1, spec.dim)[0]
        scores = _softmax([CLIP_LOGIT_SCALE * _dot(image_row, row) for row in label_rows])
        ranked = sorted(zip(labels, scores), key=lambda pair: pair[1], reverse=True)[:top_k]
        return {"contract": LOCAL_INFERENCE_CONTRACT, "model": spec.model,
                "scores": [{"label": label, "score": round(score, 6)} for label, score in ranked]}


_service_lock = threading.Lock()
_service: LocalInferenceService | None = None


def service() -> LocalInferenceService:
    global _service
    with _service_lock:
        if _service is None:
            _service = LocalInferenceService()
        return _service


def set_service(value: LocalInferenceService | None) -> None:
    global _service
    with _service_lock:
        _service = value


register_process_state(__name__, partial(set_service, None), holds=("_service",))
