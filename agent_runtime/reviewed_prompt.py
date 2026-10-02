"""Validate reviewed context before native admission; never dereference client paths."""
from __future__ import annotations

import base64
import binascii
import json

from .conversations.model import ConversationError, Refusal

__layer__ = "policy"
MAX_PROMPT_BYTES = 900 * 1024


def validate(prompt: dict) -> None:
    if not isinstance(prompt, dict) or set(prompt) != {"text", "images"}:
        raise ConversationError(Refusal.INVALID_REQUEST)
    if not isinstance(prompt["text"], str) or not isinstance(prompt["images"], list):
        raise ConversationError(Refusal.INVALID_REQUEST)
    if len(json.dumps(prompt, ensure_ascii=True, separators=(",", ":"))) > MAX_PROMPT_BYTES:
        raise ConversationError(Refusal.INVALID_REQUEST)
    for image in prompt["images"]:
        if not isinstance(image, dict) or set(image) != {"name", "data"}:
            raise ConversationError(Refusal.INVALID_REQUEST)
        if not isinstance(image["name"], str) or not isinstance(image["data"], str):
            raise ConversationError(Refusal.INVALID_REQUEST)
        try:
            base64.b64decode(image["data"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ConversationError(Refusal.INVALID_REQUEST) from exc
