"""Bound visible text without flattening native image blocks."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agent.message_content import flatten_message_text
from ..operator_input import REVIEWED_INPUT_KIND
from ..reviewed_prompt import MAX_PROMPT_BYTES
from .bounds import (
    BoundedUserContent, _MAX_USER_ROW_CONTENT, _bounded_free_text,
    bound_composed_user_content,
)

__layer__ = "policy"


@dataclass(frozen=True)
class WireContent:
    value: str | list[dict[str, Any]]
    text: BoundedUserContent
    submitted_chars: int


def bound_message_content(message: dict, *, role: str) -> WireContent:
    raw = message.get("content")
    text = flatten_message_text(raw)
    reviewed = role == "user" and message.get("display_kind") == REVIEWED_INPUT_KIND
    budget = ({"message_limit": MAX_PROMPT_BYTES,
               "row_limit": MAX_PROMPT_BYTES + _MAX_USER_ROW_CONTENT}
              if reviewed else {})
    bounded = (bound_composed_user_content(text, **budget)
               if role == "user" else _bounded_free_text(text))
    if not isinstance(raw, list):
        return WireContent(bounded.text, bounded, len(text))
    # Admission validates the image bytes. History keeps their native shape;
    # previews and accounting read only text, never a base64 representation.
    images = [deepcopy(part) for part in raw
              if role == "user" and isinstance(part, dict)
              and part.get("type") == "image_url"
              and isinstance(part.get("image_url"), dict)]
    parts = [{"type": "text", "text": bounded.text}, *images]
    return WireContent(parts, bounded, len(text))
