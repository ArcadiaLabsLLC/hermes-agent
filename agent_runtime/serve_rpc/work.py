"""``runtime.work.cancel`` / ``runtime.work.restart`` — Stop and Restart as direct methods (OWNER call 3);
``runtime.work.background.promote`` — Send to background (RT-LONG-TOOL-CALLS-BACKGROUND).

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §7. Each is the
SAME decision the argv verb reaches (``harness work cancel`` / ``harness work restart``):
``running_work.cancel_work`` and ``builds.control.restart_build``, behind the ONE ``issued_at``
replay guard both doors share (``running_work.surface._cancel_is_superseded``) — a command
issued before this work started cannot have been aimed at it. ``console`` tier. A detected
build's Restart takes no confirm parameter: the row already shows what it will run (call 2).
"""

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

#: The owning lane accepted cancellation; its payload retains the exact outcome
#: (including asynchronous requests and dispatches that had already finished).
_CANCEL_ACCEPTED = frozenset({"ok", "cancelled", "cancel_requested"})


def _row_or_refusal(rid, params):
    from agent_runtime.running_work import find_work_row
    from agent_runtime.running_work.surface import _cancel_is_superseded

    work_id = params.get("work_id")
    if not isinstance(work_id, str) or not work_id.strip():
        return None, err(rid, ERR_INVALID_PARAMS, "work_id is required.", {"reason": "invalid_request"})
    row = find_work_row(work_id)
    if row is None:
        return None, err(rid, ERR_NOT_FOUND, "No running work with that id.", {"reason": "not_found", "work_id": work_id})
    if _cancel_is_superseded(str(params.get("issued_at") or ""), str(row.get("started_at") or "")):
        return None, err(rid, ERR_CONFLICT, "Issued before this work started; superseded.",
                         {"reason": "stale_revision", "work_id": work_id, "started_at": row.get("started_at")})
    return row, None


@method("runtime.work.cancel", tier=TIER_CONSOLE)
def _runtime_work_cancel(rid, params, context=None):
    from agent_runtime.running_work import cancel_work

    row, refusal = _row_or_refusal(rid, params or {})
    if refusal is not None:
        return refusal
    result = cancel_work(row["work_id"], reason=str((params or {}).get("reason") or "operator_cancel"))
    if result.get("status") in _CANCEL_ACCEPTED:
        return ok(rid, result)
    return err(rid, ERR_CONFLICT, "The work could not be stopped.",
               {"reason": result.get("code") or "cancel_failed", "detail": result.get("detail") or ""})


@method("runtime.work.restart", tier=TIER_CONSOLE)
def _runtime_work_restart(rid, params, context=None):
    from agent_runtime.builds.control import restart_build

    row, refusal = _row_or_refusal(rid, params or {})
    if refusal is not None:
        return refusal
    if row.get("kind") != "build":
        return err(rid, ERR_CONFLICT, "Only a build can be restarted.", {"reason": "restart_unsupported"})
    result = restart_build(row)
    if result.get("status") == "restarted":
        return ok(rid, result)
    return err(rid, ERR_CONFLICT, "The build could not be restarted.",
               {"reason": result.get("detail") or result.get("code") or "restart_failed", "code": result.get("code")})


@method("runtime.work.background.promote", tier=TIER_CONSOLE)
def _runtime_work_background_promote(rid, params, context=None):
    """Send a running foreground tool call to the background now (``tools/long_tool_calls.py``).

    Params: ``work_id`` — the chat turn's (``chat_turn:<turn_id>``, then ``tool_call_id`` names its
    ``current_tool``) or a foreground ``tool_call`` child's (``tool_call:<turn_id>:<call_id>``).
    The call returns ``running_in_background`` to its turn within one poll; Cancel on the promoted
    row is ``runtime.work.cancel``. Refusals: ``invalid_request``, ``not_promotable``.
    """

    from agent_runtime.running_work import split_work_id

    params = params or {}
    kind, stable = split_work_id(str(params.get("work_id") or ""))
    if kind == "chat_turn":
        turn_id, call_id = stable, str(params.get("tool_call_id") or "")
    elif kind == "tool_call" and not stable.startswith("bg:"):
        turn_id, _sep, call_id = stable.partition(":")
    else:
        turn_id = call_id = ""
    if not turn_id or not call_id:
        return err(rid, ERR_INVALID_PARAMS, "work_id (a chat turn with tool_call_id, or a foreground tool call) is required.",
                   {"reason": "invalid_request"})
    from tools.long_tool_calls import request_promotion

    answer = request_promotion(turn_id, call_id)
    if answer.get("status") == "ok":
        return ok(rid, {**answer, "work_id": params.get("work_id")})
    return err(rid, ERR_CONFLICT, "That tool call cannot be sent to the background.",
               {"reason": answer.get("code") or "not_promotable", "detail": answer.get("detail") or ""})
