"""Pasted images on the operator chat send: bounded PNG/JPEG parts in, image parts to a vision model.

Row ``RT-OPERATOR-CHAT-SEND-PERSONA`` (hermes ``runtime-queue.md``; the launcher half is
``MC-PASTED-IMAGE``). The path, end to end:

1. **The door.** ``runtime.chat.message`` accepts ``images: [{media_type, data_b64}]``
   (:func:`normalize_images`): at most :data:`MAX_IMAGES`, each at most :data:`MAX_IMAGE_BYTES`
   decoded, ``image/png`` or ``image/jpeg`` only, the bytes' magic matching the declared type
   (the launcher converts BMP / clipboard formats first). Refusals are typed:
   ``image_invalid`` / ``image_too_large``.
2. **The store.** The bytes are written content-addressed (:func:`store_images`) under
   ``<store root>/operator_images/<sha256>.<ext>`` and the send's argv names each by reference
   (``--image sha256:<hex>.png``), never by path and never by bytes — so the turn's fingerprint
   covers the images, a replay of the same send names the same files, and no path crosses a door.
3. **The turn.** ``mission-chat message`` resolves each reference (:func:`resolve_refs`; a
   reference that names nothing is ``image_invalid``) and asks the model metadata whether the
   model this turn runs on takes images (:func:`vision_supported`: upstream's
   ``agent.image_routing.decide_image_input_mode``, which reads ``agent.image_input_mode`` and the
   model's capability record). ``text`` is the typed refusal ``vision_unsupported``, before any
   token is spent.
4. **The provider.** ``AgentRunRequest.user_image_paths`` -> :func:`native_user_message`: upstream's
   ``build_native_content_parts`` turns the composed user text plus the paths into OpenAI-style
   content parts; the persisted row is the text with one ``MEDIA:<path>`` line per image
   (:func:`media_lines`), which is what the bubble renders and what puts the file in
   ``runtime.media.get``'s derived scope (``agent_runtime/media_handles.py``).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

__layer__ = "policy"

MAX_IMAGES = 4
#: 5 MiB decoded: ``media_handles.MAX_FETCH_BYTES`` (``api_server._MEDIA_DATA_URL_MAX_BYTES``) —
#: the same question about the same bytes, so the same number.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
#: media type -> (magic prefix, stored extension). PNG and JPEG only (row ruling).
ACCEPTED_TYPES: dict[str, tuple[bytes, str]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
}
IMAGES_DIRNAME = "operator_images"
IMAGE_FLAG = "--image"
_REF_RE = re.compile(r"^sha256:([0-9a-f]{64})(\.png|\.jpg)$")

REASON_IMAGE_INVALID = "image_invalid"
REASON_IMAGE_TOO_LARGE = "image_too_large"
REASON_VISION_UNSUPPORTED = "vision_unsupported"


class OperatorImagesInvalid(ValueError):
    """A refusable image part. ``reason`` is what a client branches on."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class OperatorImage:
    media_type: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def ref(self) -> str:
        return f"sha256:{self.sha256}{ACCEPTED_TYPES[self.media_type][1]}"


def normalize_images(raw: Any) -> list[OperatorImage]:
    """The ``images`` param -> validated parts. Absent / empty -> ``[]``. Refusals typed."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OperatorImagesInvalid(REASON_IMAGE_INVALID, "invalid params: images must be a list when sent")
    if len(raw) > MAX_IMAGES:
        raise OperatorImagesInvalid(REASON_IMAGE_INVALID, f"invalid params: at most {MAX_IMAGES} images per send")
    return [_one_image(index, part) for index, part in enumerate(raw)]


def _one_image(index: int, part: Any) -> OperatorImage:
    where = f"images[{index}]"
    if not isinstance(part, dict):
        raise OperatorImagesInvalid(REASON_IMAGE_INVALID, f"invalid params: {where} must be an object")
    media_type = part.get("media_type")
    if media_type not in ACCEPTED_TYPES:
        raise OperatorImagesInvalid(
            REASON_IMAGE_INVALID, f"invalid params: {where}.media_type must be one of {sorted(ACCEPTED_TYPES)}")
    encoded = part.get("data_b64")
    if not isinstance(encoded, str) or not encoded:
        raise OperatorImagesInvalid(REASON_IMAGE_INVALID, f"invalid params: {where}.data_b64 must be base64 text")
    # A cheap ceiling before decoding: base64 is 4 chars per 3 bytes.
    if len(encoded) > (MAX_IMAGE_BYTES // 3 + 1) * 4 + 4:
        raise OperatorImagesInvalid(REASON_IMAGE_TOO_LARGE, f"invalid params: {where} exceeds {MAX_IMAGE_BYTES} bytes")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise OperatorImagesInvalid(REASON_IMAGE_INVALID, f"invalid params: {where}.data_b64 is not base64") from None
    if len(data) > MAX_IMAGE_BYTES:
        raise OperatorImagesInvalid(REASON_IMAGE_TOO_LARGE, f"invalid params: {where} exceeds {MAX_IMAGE_BYTES} bytes")
    if not data.startswith(ACCEPTED_TYPES[media_type][0]):
        raise OperatorImagesInvalid(
            REASON_IMAGE_INVALID, f"invalid params: {where} bytes are not a {media_type} (magic mismatch)")
    return OperatorImage(media_type=media_type, data=data)


def images_dir(store_root: Path | None = None) -> Path:
    if store_root is None:
        from . import paths

        store_root = paths.store_root()
    return Path(store_root) / IMAGES_DIRNAME


def store_images(images: Iterable[OperatorImage], *, store_root: Path | None = None) -> list[str]:
    """Write each image content-addressed (idempotent) and return its reference, in order."""
    refs: list[str] = []
    directory = None
    for image in images:
        directory = directory or images_dir(store_root)
        target = directory / image.ref.removeprefix("sha256:")
        if not target.is_file():
            directory.mkdir(parents=True, exist_ok=True)
            from utils import atomic_write_bytes

            atomic_write_bytes(target, image.data)
        refs.append(image.ref)
    return refs


def resolve_refs(refs: Iterable[str] | None, *, store_root: Path | None = None) -> list[Path]:
    """``--image`` references -> stored files. A malformed or dangling reference is ``image_invalid``."""
    resolved: list[Path] = []
    for ref in refs or ():
        match = _REF_RE.match(str(ref or ""))
        if match is None:
            raise OperatorImagesInvalid(REASON_IMAGE_INVALID, f"image reference {str(ref)[:80]!r} is malformed")
        path = images_dir(store_root) / f"{match.group(1)}{match.group(2)}"
        if not path.is_file():
            raise OperatorImagesInvalid(REASON_IMAGE_INVALID, f"image {match.group(1)[:12]} is not stored on this install")
        resolved.append(path)
    if len(resolved) > MAX_IMAGES:
        raise OperatorImagesInvalid(REASON_IMAGE_INVALID, f"at most {MAX_IMAGES} images per send")
    return resolved


def vision_supported(provider: str, model: str, *, requested_provider: str = "") -> bool:
    """Does the model this turn runs on take image parts? Upstream's decision, never a fork table."""
    from agent.image_routing import decide_image_input_mode
    from hermes_cli.config import load_config

    try:
        cfg = load_config()
    except Exception:
        cfg = None
    return decide_image_input_mode(
        str(provider or "").strip(), str(model or "").strip(), cfg, requested_provider=requested_provider,
    ) == "native"


def media_lines(paths: Iterable[Path | str]) -> str:
    """One ``MEDIA:<path>`` line per image: the bubble's rendering and ``runtime.media.get``'s scope."""
    return "\n".join(f"MEDIA:{path}" for path in paths)


def with_media_lines(text: str, paths: Iterable[Path | str]) -> str:
    lines = media_lines(paths)
    return f"{text}\n\n{lines}" if lines else text


def native_user_message(text: str, paths: Iterable[Path | str]) -> tuple[Any, str]:
    """``(user_message, persist_user_message)`` for a turn carrying images.

    The provider sees upstream's content parts (text + ``image_url`` data URLs); the transcript
    keeps the text with the ``MEDIA:`` lines, never a data URL. With no readable image the turn
    is the plain text (upstream reports the skip; the reference was already proven stored)."""
    from agent.image_routing import build_native_content_parts

    path_list = [str(path) for path in paths]
    parts, _skipped = build_native_content_parts(text, path_list)
    persisted = with_media_lines(text, path_list)
    if not any(part.get("type") == "image_url" for part in parts):
        return text, persisted
    return parts, persisted
