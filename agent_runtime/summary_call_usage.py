"""The iteration-summary call's usage, read at the HTTP client the fork already hooks.

Row ``RT-ITERATION-SUMMARY-CALL-UNCOUNTED``. When a turn runs out of iterations — the iteration
limit, the wall checkpoint, a Lens token budget (``turn_token_budget``) — upstream's finalizer makes
one toolless "summarise" request (``agent/chat_completion_helpers.py::handle_max_iterations``). That
request fires no ``post_api_request``, so its tokens reached no fork reader: not the turn's usage
ledger (the turn record's ``provider_usage``) and not an armed token budget.

Every provider request of a turn goes through a per-request client that
``transport_phase_trace.install_transport_phase_trace`` already hooks (the fork seam in
``agent/client_lifecycle.py`` and ``agent/codex_runtime.py``). This module adds one httpx RESPONSE
hook there. It acts only on a request whose LAST message is upstream's summary nudge
(``agent.context_compressor.MAX_ITERATIONS_SUMMARY_REQUEST``, the constant upstream shares so readers
can recognise that nudge): the response body is teed as the SDK reads it (streaming is untouched),
and when it ends the ``usage`` it carries — a JSON body's, or the last usage-bearing SSE event's
(chat-completions final chunk, Responses ``response.completed``, Anthropic ``message_start`` +
``message_delta``) — is normalised (``agent.usage_pricing.normalize_usage``) and recorded through
``usage_ledger.record_usage``, the same door the Codex accrual site uses. Main-loop calls are never
matched, so nothing is counted twice. Fail-open everywhere.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

__layer__ = "policy"

__all__ = ["install_summary_usage_hook", "is_summary_request", "usage_from_body"]

logger = logging.getLogger(__name__)

_HOOK_MARK = "_hermes_summary_usage_hook"
#: The most of one summary response the tee keeps (a summary is a short toolless reply).
_MAXIMUM_BYTES = 8 * 1024 * 1024


def _nudge() -> str:
    from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST

    return MAX_ITERATIONS_SUMMARY_REQUEST


def _summary_nudge_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return ""


def is_summary_request(body: Any) -> bool:
    """True when the request's last message is the iteration-summary nudge."""

    if not isinstance(body, dict):
        return False
    messages = body.get("messages") if isinstance(body.get("messages"), list) else body.get("input")
    if not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict):
        return False
    last = messages[-1]
    return last.get("role") == "user" and _summary_nudge_text(last.get("content")).strip() == _nudge()


def _request_body(request: Any) -> Any:
    try:
        content = request.content
    except Exception:  # a streamed request body: not the SDK's JSON request
        return None
    if not content or json.dumps(_nudge())[1:-1].encode() not in content:
        return None  # the cheap screen: almost every request stops here
    try:
        return json.loads(content)
    except Exception:
        return None


def _merge_usage(into: dict[str, Any], usage: Any) -> None:
    if isinstance(usage, dict):
        for key, value in usage.items():
            if value not in (None, 0) or key not in into:
                into[key] = value


def usage_from_body(raw: bytes) -> dict[str, Any] | None:
    """The ``usage`` a JSON or SSE response body carries, or None."""

    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            usage = json.loads(text).get("usage")
        except Exception:
            return None
        return usage if isinstance(usage, dict) and usage else None
    merged: dict[str, Any] = {}
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        for usage in (event.get("usage"), (event.get("response") or {}).get("usage")
                      if isinstance(event.get("response"), dict) else None,
                      (event.get("message") or {}).get("usage") if isinstance(event.get("message"), dict) else None):
            _merge_usage(merged, usage)
    return merged or None


def _record_summary_usage(agent: Any, raw: bytes) -> None:
    try:
        usage = usage_from_body(raw)
        if usage is None:
            return
        from agent.usage_pricing import normalize_usage

        from .usage_ledger import record_usage

        canonical = normalize_usage(usage, provider=getattr(agent, "provider", None),
                                    api_mode=getattr(agent, "api_mode", None))
        record_usage(canonical)
    except Exception:
        logger.debug("summary call usage not recorded", exc_info=True)


class _Tee(httpx.SyncByteStream):
    """The response's byte stream, unchanged for the SDK, with a copy kept for the usage read."""

    def __init__(self, inner: Any, agent: Any) -> None:
        self._inner, self._agent = inner, agent
        self._chunks: list[bytes] = []
        self._size = 0
        self._done = False

    def __iter__(self):
        for chunk in self._inner:
            if self._size < _MAXIMUM_BYTES:
                self._chunks.append(chunk)
                self._size += len(chunk)
            yield chunk
        self._finish()

    def close(self) -> None:
        try:
            close = getattr(self._inner, "close", None)
            if callable(close):
                close()
        finally:
            self._finish()

    def _finish(self) -> None:
        if not self._done:
            self._done = True
            _record_summary_usage(self._agent, b"".join(self._chunks))


def install_summary_usage_hook(http_client: Any, agent_attr: str) -> None:
    """Add the response hook to ``http_client`` once; the turn's agent is read from ``agent_attr``."""

    hooks = getattr(http_client, "event_hooks", None)
    if not isinstance(hooks, dict) or any(getattr(hook, _HOOK_MARK, False) for hook in hooks.get("response", ())):
        return

    def _on_response(response: Any) -> None:
        try:
            if not is_summary_request(_request_body(response.request)):
                return
            stream = response.stream
            if not hasattr(stream, "__iter__"):
                return  # an async stream: the persona turn's clients are sync
            response.stream = _Tee(stream, getattr(http_client, agent_attr, None))
        except Exception:
            logger.debug("summary usage hook skipped", exc_info=True)

    setattr(_on_response, _HOOK_MARK, True)
    http_client.event_hooks = {**hooks, "response": [*hooks.get("response", ()), _on_response]}
