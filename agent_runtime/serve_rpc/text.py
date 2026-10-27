"""``runtime.text.summarize`` — one auxiliary-task summary through the user's own model.

A translation shim over :mod:`agent_runtime.text_summary`; the contract a client integrates
from is ``docs/agent-runtime-harness/runtime-text-methods.md``. The completion is a model call
that can take tens of seconds, so the reply is deferred onto the transport's worker lane when
it has one. Tier ``console``: the call spends the user's inference.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import (
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    RpcContext,
    defer_or_inline,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["_runtime_text_summarize"]

_METHOD = "runtime.text.summarize"
_CODES = {"invalid_params": ERR_INVALID_PARAMS}


def _summary_frame(rid: Any, params: Any) -> dict:
    from agent_runtime.text_summary import SummaryRefused, summarize

    try:
        return ok(rid, summarize(params))
    except SummaryRefused as refusal:
        return err(rid, _CODES.get(refusal.code, ERR_HANDLER_FAILED), f"{_METHOD} refused: {refusal.reason}",
                   {"reason": refusal.reason})
    except Exception as exc:  # the class name only: provider text never rides the wire
        return err(rid, ERR_HANDLER_FAILED, f"{_METHOD} failed",
                   {"reason": "handler_failed", "method": _METHOD, "error_class": type(exc).__name__})


@method(_METHOD, tier=TIER_CONSOLE)
def _runtime_text_summarize(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Summarize a window of lines. Params: ``task`` (``message_digest``), ``lines``
    (``[{at, speaker, text}]``), ``max_bullets``, ``locale``. Result:
    ``{contract, text, model, provider, truncated}``."""
    return defer_or_inline(rid, _METHOD, context, lambda: _summary_frame(rid, params))
