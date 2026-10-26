"""Display projection of composed operator text followed by native media markers."""
import re
from typing import Any

from ..runtime_hud.envelopes import extract_runtime_context_envelope, extract_skill_preload_envelope

__layer__ = "policy"

# Native image persistence appends these markers after the composed text. Keep
# them byte-for-byte, but let the existing end-anchored envelope readers see the
# composed text first. Ordinary prose after a quoted envelope stays untouched.
_NATIVE_MEDIA_TAIL = re.compile(
    r'(?:\r?\n+(?:\[Image attached(?: at)?: [^\r\n]+\]|'
    r'\[screenshot(?: detail=(?:low|high|auto))?\]|MEDIA:[^\r\n]+))+\s*\Z'
)


def strip_operator_envelopes(content: Any, *, include_media: bool = True) -> tuple[str, Any, Any]:
    text = content if isinstance(content, str) else str(content or "")
    tail = _NATIVE_MEDIA_TAIL.search(text)
    composed, media = (text[:tail.start()], tail.group()) if tail else (text, "")
    composed, runtime_context = extract_runtime_context_envelope(composed)
    composed, skill_preload = extract_skill_preload_envelope(composed)
    return composed + (media if include_media else ""), runtime_context, skill_preload
