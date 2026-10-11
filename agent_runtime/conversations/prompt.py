"""Validate reviewed context before native admission; never dereference client paths."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re

from .model import ConversationError, Refusal

__layer__ = "lanes"
#: Bounds ``text`` + ``images`` serialized; files are measured decoded, below.
MAX_PROMPT_BYTES = 900 * 1024

#: Reviewed-file limits. The aggregate is the launcher composer's own bound
#: (``EterniaLauncher/packages/agents/eternia_agent_client/lib/src/conversation/
#: agent_attachment.dart`` ``AgentAttachmentLimits``: count 8, 256 KiB per file,
#: 512 KiB total), so server and UI agree (owner ruling D2.01, 2026-10-10).
MAX_FILE_COUNT = 8
MAX_FILE_BYTES = 256 * 1024
MAX_FILES_TOTAL_BYTES = 512 * 1024
#: ``text/*`` admits every text subtype; the rest are exact.
FILE_MEDIA_TYPES = ("text/*", "application/json", "application/xml", "application/yaml",
                    "text/csv", "application/pdf")
PDF_MEDIA_TYPE = "application/pdf"
_FILE_KEYS = {"name", "media_type", "data"}
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")
_MEDIA_TOKEN = re.compile(r"[a-z0-9][a-z0-9.+-]*")


def files_capability() -> dict:
    return {"max_count": MAX_FILE_COUNT, "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_FILES_TOTAL_BYTES, "media_types": list(FILE_MEDIA_TYPES)}


def validate(prompt: dict) -> list[dict]:
    """Refuse a malformed packet; answer each file's server-computed identity."""
    if not isinstance(prompt, dict) or set(prompt) - {"files"} != {"text", "images"}:
        raise ConversationError(Refusal.INVALID_REQUEST)
    if not isinstance(prompt["text"], str) or not isinstance(prompt["images"], list):
        raise ConversationError(Refusal.INVALID_REQUEST)
    bounded = {"text": prompt["text"], "images": prompt["images"]}
    if len(json.dumps(bounded, ensure_ascii=True, separators=(",", ":"))) > MAX_PROMPT_BYTES:
        raise ConversationError(Refusal.INVALID_REQUEST)
    for image in prompt["images"]:
        if not isinstance(image, dict) or set(image) != {"name", "data"}:
            raise ConversationError(Refusal.INVALID_REQUEST)
        if not isinstance(image["name"], str) or not isinstance(image["data"], str):
            raise ConversationError(Refusal.INVALID_REQUEST)
        _decoded_or_refuse(image["data"], Refusal.INVALID_REQUEST)
    return _validate_files(prompt.get("files", []))


def _validate_files(files) -> list[dict]:
    if not isinstance(files, list):
        raise ConversationError(Refusal.INVALID_REQUEST)
    if len(files) > MAX_FILE_COUNT:
        raise ConversationError(Refusal.FILE_OVERSIZE)
    identities, total = [], 0
    for item in files:
        if not isinstance(item, dict) or set(item) != _FILE_KEYS or not all(
                isinstance(item[key], str) for key in _FILE_KEYS):
            raise ConversationError(Refusal.INVALID_REQUEST)
        name = item["name"]
        if not name or len(name) > 200 or _UNSAFE_NAME.search(name):
            raise ConversationError(Refusal.FILE_INVALID)
        if not media_type_allowed(item["media_type"]):
            raise ConversationError(Refusal.FILE_UNSUPPORTED)
        payload = _decoded_or_refuse(item["data"], Refusal.FILE_INVALID)
        if not payload:
            raise ConversationError(Refusal.FILE_INVALID)
        total += len(payload)
        if len(payload) > MAX_FILE_BYTES or total > MAX_FILES_TOTAL_BYTES:
            raise ConversationError(Refusal.FILE_OVERSIZE)
        identities.append({"name": name, "media_type": item["media_type"],
                           "size_bytes": len(payload),
                           "sha256": hashlib.sha256(payload).hexdigest()})
    return identities


def media_type_allowed(media_type: str) -> bool:
    kind, _, subtype = media_type.partition("/")
    if not (_MEDIA_TOKEN.fullmatch(kind) and _MEDIA_TOKEN.fullmatch(subtype)):
        return False
    return media_type in FILE_MEDIA_TYPES or f"{kind}/*" in FILE_MEDIA_TYPES


def _decoded_or_refuse(data: str, refusal: Refusal) -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ConversationError(refusal) from exc


def submit(peer, native_id: str, prompt: dict, execution_id: str) -> None:
    for image in prompt["images"]:
        attached = peer.call("image.attach_bytes", {"session_id": native_id,
            "filename": image["name"], "content_base64": image["data"]})
        if attached.get("attached") is not True:
            raise ConversationError(Refusal.NATIVE_REFUSAL)
    refs = [_attach_file(peer, native_id, item) for item in prompt.get("files", [])]
    text = "\n\n".join(part for part in (prompt["text"], *refs) if part)
    result = peer.call("prompt.submit", {"session_id": native_id, "text": text,
        "reject_if_busy": True, "execution_id": execution_id})
    if result.get("status") != "streaming":
        # A queue/steer acknowledgement is not the independent turn we admitted.
        raise ConversationError(Refusal.UNKNOWN)


def _attach_file(peer, native_id: str, item: dict) -> str:
    """Stage one reviewed file in the native session; answer the ref the agent reads it by.

    Bytes travel inline (``data_url`` / ``content_base64``), never a client path.
    """
    if item["media_type"] == PDF_MEDIA_TYPE:
        attached = peer.call("pdf.attach", {"session_id": native_id, "filename": item["name"],
                                            "content_base64": item["data"]})
        ref = attached.get("text")
    else:
        attached = peer.call("file.attach", {"session_id": native_id, "name": item["name"],
            "data_url": f"data:{item['media_type']};base64,{item['data']}"})
        ref = attached.get("ref_text")
    if attached.get("attached") is not True or not isinstance(ref, str) or not ref:
        raise ConversationError(Refusal.NATIVE_REFUSAL)
    return ref
