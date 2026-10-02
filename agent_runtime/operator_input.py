"""Lossless, reviewed input at the native chat door. Never opens client paths."""
from __future__ import annotations

import json
import base64
import warnings
from io import BytesIO
from dataclasses import dataclass

from .reviewed_prompt import ReviewedPromptError, validate

__layer__ = "policy"
MAX_MESSAGE_LENGTH = 64_000
REVIEWED_INPUT_KIND = "reviewed_context"


@dataclass(frozen=True)
class OperatorInput:
    text: str
    images: tuple[dict[str, str], ...] = ()
    reviewed: bool = False

    def argv(self) -> list[str]:
        if not self.reviewed:
            return ["--message", self.text]
        return ["--reviewed-prompt-json", json.dumps(
            {"text": self.text, "images": list(self.images)},
            ensure_ascii=True, separators=(",", ":"))]

    def content(self, composed_text: str):
        if not self.images:
            return composed_text
        return [{"type": "text", "text": composed_text}, *[
            {"type": "image_url", "image_url": {"url": image_url(image)}}
            for image in self.images]]


def image_url(image: dict[str, str]) -> str:
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(base64.b64decode(image["data"], validate=True))) as opened:
                if opened.format not in ("PNG", "JPEG", "WEBP"):
                    raise ReviewedPromptError("unsupported_image")
                mime = Image.MIME[opened.format]
                opened.verify()
    except (ValueError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ReviewedPromptError("invalid_image") from exc
    return f'data:{mime};base64,{image["data"]}'


def operator_input(message=None, prompt=None) -> OperatorInput:
    if prompt is not None:
        if message is not None:
            raise ReviewedPromptError("conflicting_input")
        validate(prompt)
        text = prompt["text"]
        images = tuple(dict(image) for image in prompt["images"])
        for image in images:
            image_url(image)
    else:
        if message is None:
            raise ReviewedPromptError("message_required")
        if not isinstance(message, str) or len(message) > MAX_MESSAGE_LENGTH:
            raise ReviewedPromptError("message_invalid")
        text, images = message.strip(), ()
    if not text.strip():
        raise ReviewedPromptError("message_required")
    if "\x00" in text:
        raise ReviewedPromptError("message_invalid")
    return OperatorInput(text, images, reviewed=prompt is not None)


def input_from_args(args) -> OperatorInput:
    raw = getattr(args, "reviewed_prompt_json", None)
    try:
        prompt = json.loads(raw) if raw is not None else None
    except (ValueError, TypeError) as exc:
        raise ReviewedPromptError("invalid_prompt") from exc
    return operator_input(getattr(args, "message", None), prompt)
