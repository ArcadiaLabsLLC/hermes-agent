"""Bounded public completion receipt, owned by the native execution journal."""
from __future__ import annotations

MAX_RESULT_BYTES = 64 * 1024


def public_result(payload: dict) -> dict:
    text = payload.get("text")
    text = text if isinstance(text, str) else ""
    encoded = text.encode("utf-8")
    clipped = encoded[:MAX_RESULT_BYTES].decode("utf-8", errors="ignore")
    error = payload.get("failure_reason")
    return {"text": clipped, "truncated": len(encoded) > MAX_RESULT_BYTES,
            "error": error if isinstance(error, str) else None}
