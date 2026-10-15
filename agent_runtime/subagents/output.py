"""Permit complete public event lines from the native bounded live log."""
import re

from agent_runtime.redaction import scrub_secret_values
from .model import TAIL_BYTES

__layer__ = "policy"

# The native writer emits one timestamped line per event. Unknown/new roles and
# partial lines are withheld, including the native `think` role and log headers.
_PUBLIC_LINE = re.compile(r"^\d{2}:\d{2}:\d{2} (assistant|tool|result|start|final)\s*\| .*$")


def read_public_tail(agent) -> dict:
    path = getattr(agent, "_live_transcript_path", None)
    result = {"available": False, "text": "", "truncated": False}
    if not path:
        return result
    try:
        with open(path, "rb") as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - TAIL_BYTES)
            stream.seek(offset)
            raw = stream.read(TAIL_BYTES)
    except OSError:
        return result
    lines = raw.split(b"\n")
    # Drop the start fragment unconditionally on a bounded seek and the final
    # unterminated line. No hidden-reasoning fragment can masquerade as output.
    complete = lines[1 if offset else 0:-1]
    text = "\n".join(line for raw_line in complete
                     if _PUBLIC_LINE.fullmatch(line := raw_line.decode("utf-8", errors="replace").rstrip("\r")))
    encoded = scrub_secret_values(text).encode("utf-8")
    return {"available": True, "text": encoded[:TAIL_BYTES].decode("utf-8", errors="ignore"),
            "truncated": bool(offset) or len(encoded) > TAIL_BYTES}
