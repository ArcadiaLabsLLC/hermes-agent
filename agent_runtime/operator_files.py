"""Reviewed files on the operator chat send: staged on disk, named to the agent by a path line.

Row ``RT-MISSION-CHAT-MESSAGE-TAKES`` (hermes ``runtime-queue.md``; the launcher half is
``MC-CONSOLE-SEND-FILES``; plan ``docs/agent-runtime-harness/archive/p10-turn-2026-10-19.md`` §3).
The mirror of :mod:`agent_runtime.operator_images`, end to end:

1. **The door.** ``runtime.chat.message`` accepts ``files: [{name, media_type, data}]`` — the
   native conversation lane's ``prompt.files`` item shape — bounded by THAT lane's constants
   (``agent_runtime/conversations/prompt.py``: count, per-file and aggregate bytes, media types),
   imported, never copied (owner ruling D2.01: one number set for server and composer). Refusals
   are the native lane's spellings (``conversations.model.Refusal``): ``file_unsupported`` /
   ``file_oversize`` / ``file_invalid``. :func:`files_limits` is what the method-lane manifest
   publishes as ``limits.files``.
2. **The store.** Bytes are written content-addressed (:func:`store_files`) under
   ``<store root>/operator_files/<sha256>.<ext>`` with a ``<sha256>.name.json`` sidecar carrying the
   display name, and the send's argv names each by reference (``--file sha256:<hex>.<ext>``) —
   never by path, never by bytes.
3. **The turn.** ``mission-chat message`` resolves each reference (:func:`resolve_refs`; a
   reference naming nothing is ``file_invalid``). The file is STAGED, never inlined (owner ruling
   2026-10-19): the user text gains one ``FILE:<path>`` line per file and one guidance sentence
   (:func:`with_file_lines`), and the agent reads what it needs with ``read_file`` (which extracts
   a PDF's text layer, so ``application/pdf`` stays published on this lane too).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .conversations.model import Refusal
from .media_handles import FILE_DECLARATION_PREFIX, OPERATOR_FILE_EXTENSIONS, OPERATOR_FILES_DIRNAME
from .conversations.prompt import (
    MAX_FILE_BYTES,
    MAX_FILE_COUNT,
    MAX_FILES_TOTAL_BYTES,
    files_capability,
    media_type_allowed,
)

__layer__ = "lanes"

#: The dirname, the line prefix and the extension table are owned by ``media_handles`` (the
#: stores layer that admits a ``FILE:`` line into ``runtime.media.get``'s derived scope).
FILES_DIRNAME = OPERATOR_FILES_DIRNAME
FILE_FLAG = "--file"
FILE_LINE_PREFIX = FILE_DECLARATION_PREFIX
#: The name sidecar beside each stored file. NOT ``<sha256>.json``: a stored ``application/json``
#: file IS ``<sha256>.json``, and the two would be one path.
SIDECAR_SUFFIX = ".name.json"
MAX_FILE_NAME = 200
#: The one sentence that tells the agent what the ``FILE:`` lines are (``{names}``: display names).
FILE_GUIDANCE = "Attached files ({names}) are on disk at the FILE: paths; read the ones you need with read_file."

#: media type -> stored extension. ``text/*`` is the family row: every admitted text subtype
#: without its own row stores as ``.txt`` — a ``.bin`` would be refused by ``read_file``'s
#: binary-extension check, and every admitted type has a row, so no ``.bin`` exists.
STORED_EXTENSIONS: dict[str, str] = OPERATOR_FILE_EXTENSIONS
_REF_RE = re.compile(r"^sha256:([0-9a-f]{64})(\.[a-z]+)$")
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")

REASON_FILE_UNSUPPORTED = Refusal.FILE_UNSUPPORTED.value
REASON_FILE_OVERSIZE = Refusal.FILE_OVERSIZE.value
REASON_FILE_INVALID = Refusal.FILE_INVALID.value


class OperatorFilesInvalid(ValueError):
    """A refusable file part. ``reason`` is one of the native lane's three file refusals."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class OperatorFile:
    name: str
    media_type: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def ref(self) -> str:
        return f"sha256:{self.sha256}{stored_extension(self.media_type)}"


@dataclass(frozen=True)
class ResolvedFile:
    path: Path
    name: str
    media_type: str
    size_bytes: int


def stored_extension(media_type: str) -> str:
    return STORED_EXTENSIONS.get(media_type) or STORED_EXTENSIONS[f"{media_type.partition('/')[0]}/*"]


def files_limits() -> dict:
    """The ``limits.files`` the manifest publishes: the native lane's capability, one owner."""
    return files_capability()


def normalize_files(raw: Any) -> list[OperatorFile]:
    """The ``files`` param -> validated parts. Absent / empty -> ``[]``. Refusals typed."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OperatorFilesInvalid(REASON_FILE_INVALID, "invalid params: files must be a list when sent")
    if len(raw) > MAX_FILE_COUNT:
        raise OperatorFilesInvalid(REASON_FILE_OVERSIZE, f"invalid params: at most {MAX_FILE_COUNT} files per send")
    files, total = [], 0
    for index, part in enumerate(raw):
        file = _one_file(index, part)
        total += len(file.data)
        if total > MAX_FILES_TOTAL_BYTES:
            raise OperatorFilesInvalid(
                REASON_FILE_OVERSIZE, f"invalid params: files exceed {MAX_FILES_TOTAL_BYTES} bytes together")
        files.append(file)
    return files


def _one_file(index: int, part: Any) -> OperatorFile:
    where = f"files[{index}]"
    if not isinstance(part, dict) or not all(isinstance(part.get(key), str) for key in ("name", "media_type", "data")):
        raise OperatorFilesInvalid(
            REASON_FILE_INVALID, f"invalid params: {where} must be an object of name, media_type, data (text)")
    name = part["name"]
    if not name or len(name) > MAX_FILE_NAME or _UNSAFE_NAME.search(name):
        raise OperatorFilesInvalid(REASON_FILE_INVALID, f"invalid params: {where}.name is empty, too long or unsafe")
    if not media_type_allowed(part["media_type"]):
        raise OperatorFilesInvalid(
            REASON_FILE_UNSUPPORTED, f"invalid params: {where}.media_type {part['media_type'][:80]!r} is not admitted")
    encoded = part["data"]
    # A cheap ceiling before decoding: base64 is 4 chars per 3 bytes.
    if len(encoded) > (MAX_FILE_BYTES // 3 + 1) * 4 + 4:
        raise OperatorFilesInvalid(REASON_FILE_OVERSIZE, f"invalid params: {where} exceeds {MAX_FILE_BYTES} bytes")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise OperatorFilesInvalid(REASON_FILE_INVALID, f"invalid params: {where}.data is not base64") from None
    if not data:
        raise OperatorFilesInvalid(REASON_FILE_INVALID, f"invalid params: {where} is empty")
    if len(data) > MAX_FILE_BYTES:
        raise OperatorFilesInvalid(REASON_FILE_OVERSIZE, f"invalid params: {where} exceeds {MAX_FILE_BYTES} bytes")
    return OperatorFile(name=name, media_type=part["media_type"], data=data)


def files_dir(store_root: Path | None = None) -> Path:
    if store_root is None:
        from . import paths

        store_root = paths.store_root()
    return Path(store_root) / FILES_DIRNAME


def store_files(files: Iterable[OperatorFile], *, store_root: Path | None = None) -> list[str]:
    """Write each file content-addressed (idempotent) plus its sidecar; return its reference, in order.

    The sidecar is keyed on the digest and written once: the same bytes sent again under another
    name keep the first name, so a replay of either send resolves the same record."""
    from utils import atomic_json_write, atomic_write_bytes

    refs: list[str] = []
    directory = None
    for file in files:
        directory = directory or files_dir(store_root)
        target = directory / file.ref.removeprefix("sha256:")
        sidecar = directory / f"{file.sha256}{SIDECAR_SUFFIX}"
        if not target.is_file() or not sidecar.is_file():
            directory.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                atomic_write_bytes(target, file.data)
            if not sidecar.is_file():
                atomic_json_write(sidecar, {"name": file.name, "media_type": file.media_type,
                                            "size_bytes": len(file.data)})
        refs.append(file.ref)
    return refs


def resolve_refs(refs: Iterable[str] | None, *, store_root: Path | None = None) -> list[ResolvedFile]:
    """``--file`` references -> stored files. A malformed or dangling reference is ``file_invalid``."""
    resolved: list[ResolvedFile] = []
    for ref in refs or ():
        match = _REF_RE.match(str(ref or ""))
        if match is None or match.group(2) not in STORED_EXTENSIONS.values():
            raise OperatorFilesInvalid(REASON_FILE_INVALID, f"file reference {str(ref)[:80]!r} is malformed")
        directory = files_dir(store_root)
        path = directory / f"{match.group(1)}{match.group(2)}"
        sidecar = _read_sidecar(directory / f"{match.group(1)}{SIDECAR_SUFFIX}")
        if not path.is_file() or sidecar is None:
            raise OperatorFilesInvalid(REASON_FILE_INVALID, f"file {match.group(1)[:12]} is not stored on this install")
        resolved.append(ResolvedFile(path=path, **sidecar))
    if len(resolved) > MAX_FILE_COUNT:
        raise OperatorFilesInvalid(REASON_FILE_OVERSIZE, f"at most {MAX_FILE_COUNT} files per send")
    return resolved


def _read_sidecar(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(raw, dict) and isinstance(raw.get("name"), str) and isinstance(raw.get("media_type"), str)
            and type(raw.get("size_bytes")) is int):
        return None
    return {"name": raw["name"], "media_type": raw["media_type"], "size_bytes": raw["size_bytes"]}


def file_lines(resolved: Iterable[ResolvedFile]) -> str:
    """One ``FILE:<path>`` line per staged file."""
    return "\n".join(f"{FILE_LINE_PREFIX}{item.path}" for item in resolved)


def with_file_lines(text: str, resolved: Iterable[ResolvedFile]) -> str:
    """``text`` + the guidance sentence (naming the files' display names) + the ``FILE:`` lines."""
    items = list(resolved)
    if not items:
        return text
    guidance = FILE_GUIDANCE.format(names=", ".join(item.name for item in items))
    return f"{text}\n\n{guidance}\n{file_lines(items)}"
