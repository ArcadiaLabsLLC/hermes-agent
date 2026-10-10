"""Native content redaction preserves provider blocks and JSON value types."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from ..redaction import TEXT_SECRET_KEYS
from .bounds import _redacted

__layer__ = "policy"


def redact_native_content(value: Any) -> Any:
    """Redact readable content, keeping opaque media/signatures byte-exact.

    A content-part list belongs to the provider: only its text leaves are ours
    to redact. The multimodal tool envelope has the same parts plus a summary.
    Other JSON tool data retains its scalar types and credential-key masking.
    """
    if isinstance(value, str):
        return _redacted(value)
    if isinstance(value, list):
        return [_redacted_part(part) for part in value]
    if isinstance(value, dict) and value.get("_multimodal") is True:
        result = deepcopy(value)
        if isinstance(value.get("content"), list):
            result["content"] = redact_native_content(value["content"])
        if isinstance(value.get("text_summary"), str):
            result["text_summary"] = _redacted(value["text_summary"])
        return result
    return _redacted_json(value)


def _redacted_part(part: Any) -> Any:
    result = deepcopy(part)
    if isinstance(part, dict) and isinstance(part.get("text"), str):
        result["text"] = _redacted(part["text"])
    elif isinstance(part, str):
        result = _redacted(part)
    return result


def _redacted_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if isinstance(key, str) and re.search(r"(?:" + TEXT_SECRET_KEYS + r")$", key, re.IGNORECASE)
            else _redacted_json(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redacted_json(child) for child in value]
    return _redacted(value) if isinstance(value, str) else deepcopy(value)


def content_text_chars(value: Any) -> int:
    """String-leaf characters, without flattening or serializing native media."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(content_text_chars(child) for child in value.values())
    if isinstance(value, list):
        return sum(content_text_chars(child) for child in value)
    return 0
