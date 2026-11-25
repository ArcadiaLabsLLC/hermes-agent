"""Display projection of composed operator text followed by native media markers."""
import copy
import functools
import re
from typing import Any

from ..operator_images import is_stored_operator_image_path, with_media_lines
from ..runtime_hud.envelopes import extract_runtime_context_envelope, extract_skill_preload_envelope

__layer__ = "policy"

# Native persistence puts the image notes and slot markers after the composed
# text. Isolate that suffix so the end-anchored envelope readers see the HUD
# and preload, and keep ordinary trailing prose in the caption.
_NATIVE_MEDIA_TAIL = re.compile(
    r'(?P<notes>(?:\r?\n+(?:\[Image attached(?: at)?: [^\r\n]+\]|MEDIA:[^\r\n]+))+)'
    r'(?P<slots>(?:\r?\n+\[screenshot(?: detail=(?:low|high|auto))?\])*)\s*\Z'
)


def _operator_media_tail(tail: re.Match[str]) -> str:
    """Project a stored upload in the same format as the live mirror."""
    slots = tail["slots"]
    if not slots:
        return tail[0]
    from agent.image_routing import split_image_notes

    notes = tail["notes"].replace("\r\n", "\n")
    preceding, paths = split_image_notes(notes)
    if (
        not paths
        or len(paths) != sum(bool(line) for line in slots.splitlines())
        or not all(is_stored_operator_image_path(path) for path in paths)
    ):
        return tail[0]
    return with_media_lines(preceding, paths)


def strip_operator_envelopes(content: Any, *, include_media: bool = True) -> tuple[str, Any, Any]:
    """The composed text, its runtime-context envelope and its skill-preload envelope.

    Kept per text (:func:`_stripped`): a chat's stored operator rows are parsed once, not
    again on every read of the chat
    (RT-FU-EVERY-NEKO-REPLY-RE-READS-THE-WHOLE-LIVE-CHAT-BEFORE-ETERNIA-SHOWS-IT). Each
    caller gets its own copies of the envelope dicts."""

    text = content if isinstance(content, str) else str(content or "")
    composed, runtime_context, skill_preload = _stripped(text, include_media)
    return composed, copy.deepcopy(runtime_context), copy.deepcopy(skill_preload)


@functools.lru_cache(maxsize=4096)
def _stripped(text: str, include_media: bool) -> tuple[str, Any, Any]:
    tail = _NATIVE_MEDIA_TAIL.search(text)
    composed = text[:tail.start()] if tail else text
    composed, runtime_context = extract_runtime_context_envelope(composed)
    composed, skill_preload = extract_skill_preload_envelope(composed)
    media = _operator_media_tail(tail) if tail and include_media else ""
    return composed + media, runtime_context, skill_preload
