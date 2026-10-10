"""Native content redaction preserves provider blocks and JSON value types."""
from __future__ import annotations

from copy import deepcopy
from functools import singledispatch
import re
from typing import Any

from ..redaction import TEXT_SECRET_KEYS
from .bounds import _redacted

__layer__ = "policy"


@singledispatch
def redact_native_content(value: Any) -> Any:
    """Redact readable content, keeping opaque media/signatures byte-exact.

    A content-part list belongs to the provider: only its text leaves are ours
    to redact. The multimodal tool envelope has the same parts plus a summary.
    Other JSON tool data retains its scalar types and credential-key masking.
    """
    return deepcopy(value)


redact_native_content.register(str, _redacted)


@redact_native_content.register(list)
def _native_parts(value: list) -> list:
    return [_redacted_part(part) for part in value]


@redact_native_content.register(dict)
def _native_mapping(value: dict) -> dict:
    if value.get("_multimodal") is True:
        result = deepcopy(value)
        if isinstance(value.get("content"), list):
            result["content"] = redact_native_content(value["content"])
        if isinstance(value.get("text_summary"), str):
            result["text_summary"] = _redacted(value["text_summary"])
        return result
    return _redacted_json(value)


def _redacted_part(part: Any) -> Any:
    if not isinstance(part, dict) or not isinstance(part.get("type"), str):
        return _redacted_json(part)
    result = deepcopy(part)
    if isinstance(part.get("text"), str):
        result["text"] = _redacted(part["text"])
    return result


@singledispatch
def _redacted_json(value: Any) -> Any:
    return deepcopy(value)


_redacted_json.register(str, _redacted)


@_redacted_json.register(dict)
def _json_mapping(value: dict) -> dict:
    return {
        key: "[redacted]"
        if isinstance(key, str) and re.search(r"(?:" + TEXT_SECRET_KEYS + r")$", key, re.IGNORECASE)
        else _redacted_json(child)
        for key, child in value.items()
    }


@_redacted_json.register(list)
def _json_sequence(value: list) -> list:
    return [_redacted_json(child) for child in value]


@singledispatch
def content_text_chars(value: Any) -> int:
    """String-leaf characters, without flattening or serializing native media."""
    return 0


content_text_chars.register(str, len)


@content_text_chars.register(dict)
def _mapping_chars(value: dict) -> int:
    return sum(content_text_chars(child) for child in value.values())


@content_text_chars.register(list)
def _sequence_chars(value: list) -> int:
    return sum(content_text_chars(child) for child in value)
