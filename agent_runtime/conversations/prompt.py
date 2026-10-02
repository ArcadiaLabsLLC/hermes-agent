"""Validate reviewed context before native admission; never dereference client paths."""
from __future__ import annotations

from .model import ConversationError, Refusal

__layer__ = "lanes"


def submit(peer, native_id: str, prompt: dict, execution_id: str) -> None:
    for image in prompt["images"]:
        attached = peer.call("image.attach_bytes", {"session_id": native_id,
            "filename": image["name"], "content_base64": image["data"]})
        if attached.get("attached") is not True:
            raise ConversationError(Refusal.NATIVE_REFUSAL)
    result = peer.call("prompt.submit", {"session_id": native_id, "text": prompt["text"],
        "reject_if_busy": True, "execution_id": execution_id})
    if result.get("status") != "streaming":
        # A queue/steer acknowledgement is not the independent turn we admitted.
        raise ConversationError(Refusal.UNKNOWN)
