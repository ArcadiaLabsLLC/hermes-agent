"""Carry native error classification on its terminal result, never on the agent."""

from typing import Any

from agent.error_classifier import ClassifiedError


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
            block[key] = value
    result["provider_error"] = block
