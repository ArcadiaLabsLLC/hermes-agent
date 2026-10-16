"""Carry native error classification on its terminal result, never on the agent."""

from typing import Any

from agent.api_error_summary import ApiErrorSummaryMixin
from agent.error_classifier import ClassifiedError


class _ProviderBody(Exception):
    """A provider's raw error text with its status, for the shared one-line summariser."""

    def __init__(self, text: str, status_code: int | None) -> None:
        super().__init__(text)
        self.status_code = status_code


def _block_message(value: str, status_code: int | None) -> str:
    """The block's ``message``: an HTML error page becomes the summary the serve logs
    (``HTTP 404 — Not Found``); the page itself stays in the log, never on the wire."""
    if "<!DOCTYPE" in value or "<html" in value:
        return ApiErrorSummaryMixin._summarize_api_error(_ProviderBody(value, status_code))
    return value


def attach_provider_failure(
    result: dict[str, Any] | None,
    classified: ClassifiedError | None,
    context: dict[str, Any],
) -> None:
    if classified is None or not result or not result.get("failed") or result.get("interrupted"):
        return
    evidence = {**context, **classified.error_context}
    block = {
        "status_code": classified.status_code,
        "provider": classified.provider,
        "model": classified.model,
        "failure_reason": result.get("failure_reason") or classified.reason.value,
    }
    # Reuse parsed provider evidence; do not serialize SDK objects or request headers.
    for key in ("reason", "message", "reset_at"):
        value = evidence.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            block[key] = _block_message(value, classified.status_code) if key == "message" and isinstance(value, str) else value
    result["provider_error"] = block
