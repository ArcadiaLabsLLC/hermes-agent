"""Carry native error classification on its terminal result, never on the agent."""

import re
from typing import Any

from agent.error_classifier import ClassifiedError

_HTML_TITLE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _block_message(value: str, status_code: int | None) -> str:
    """The block's ``message``: an HTML error page becomes the one line the serve logs for
    it (``HTTP 404 — Not Found``, the shape ``ApiErrorSummaryMixin`` writes); the page
    itself stays in the log, never on the wire."""
    if "<!DOCTYPE" not in value and "<html" not in value:
        return value
    match = _HTML_TITLE.search(value)
    title = match.group(1).strip() if match else "HTML error page (title not found)"
    return f"HTTP {status_code} — {title}" if status_code else title


def provider_detail_code(error: Exception) -> str | None:
    """Read the provider's specific refusal code independently of retry policy."""
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return None
    payload = body.get("error", body)
    details = payload.get("details") if isinstance(payload, dict) else None
    code = details.get("error_code") if isinstance(details, dict) else None
    return code.strip() if isinstance(code, str) and code.strip() else None


def provider_failure_block(
    classified: ClassifiedError,
    context: dict[str, Any] | None,
    *,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """The ``provider_error`` block for *classified*: what a terminal result carries, and what a
    retry wait announces while the turn is still alive (``agent_runtime.provider_retry_wait``)."""
    evidence = {**(context or {}), **classified.error_context}
    block = {
        "status_code": classified.status_code,
        "provider": classified.provider,
        "model": classified.model,
        "failure_reason": failure_reason or classified.reason.value,
    }
    # Reuse parsed provider evidence; do not serialize SDK objects or request headers.
    for key in ("reason", "message", "reset_at"):
        value = evidence.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            block[key] = _block_message(value, classified.status_code) if key == "message" and isinstance(value, str) else value
    if detail_code := evidence.get("provider_detail_code"):
        block["reason"] = detail_code
    return block


def attach_provider_failure(
    result: dict[str, Any] | None,
    classified: ClassifiedError | None,
    context: dict[str, Any],
) -> None:
    if classified is None or not result or not result.get("failed") or result.get("interrupted"):
        return
    result["provider_error"] = provider_failure_block(
        classified, context, failure_reason=result.get("failure_reason"),
    )
