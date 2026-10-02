"""Validate reviewed context before native admission; never dereference client paths."""
from __future__ import annotations

import base64
import binascii
import json

__layer__ = "policy"
MAX_PROMPT_BYTES = 900 * 1024


class ReviewedPromptError(ValueError):
    """Reviewed content is invalid or exceeds the transport limit."""


def validate(prompt: dict) -> None:
    if not isinstance(prompt, dict) or set(prompt) != {"text", "images"}:
        raise ReviewedPromptError("invalid_prompt")
    if not isinstance(prompt["text"], str) or not isinstance(prompt["images"], list):
        raise ReviewedPromptError("invalid_prompt")
    if len(json.dumps(prompt, ensure_ascii=True, separators=(",", ":"))) > MAX_PROMPT_BYTES:
        raise ReviewedPromptError("prompt_too_large")
    for image in prompt["images"]:
        if not isinstance(image, dict) or set(image) != {"name", "data"}:
            raise ReviewedPromptError("invalid_image")
        if not isinstance(image["name"], str) or not isinstance(image["data"], str):
            raise ReviewedPromptError("invalid_image")
        try:
            base64.b64decode(image["data"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ReviewedPromptError("invalid_image") from exc
