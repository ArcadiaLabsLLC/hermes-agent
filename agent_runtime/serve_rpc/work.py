"""``runtime.work.cancel`` / ``runtime.work.restart`` — Stop and Restart as direct methods (OWNER call 3);
``runtime.work.background.promote`` — Send to background (RT-LONG-TOOL-CALLS-BACKGROUND).

**These three act on what is RUNNING NOW, not on board tasks** (RT-WORK-WORD-MEANS-TASKS-AND-RUNNING-THINGS,
owner 2026-11-12: "Task" for a board item, "Running now" for what is executing). They share the
``runtime.work.`` prefix with the Task methods (``agent_runtime/work/rpc.py``: ``runtime.work.list``,
``.claim``, ``.done`` … — rows of a workspace board) only by history. Their ``work_id`` is a running-now
id (``<kind>:<id>`` from the ``running_work`` projection — ``terminal:``, ``build:``, ``delegation:``,
``chat_turn:``, ``tool_call:``); a Task is named by ``(slot, ID)``. The id spaces are disjoint and each
method takes only its own kind, so the words in every message below say "running".

Plan ``docs/agent-runtime-harness/archive/build-running-work-2026-10-04.md`` §7. Each is the
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
        return None, err(rid, ERR_NOT_FOUND, "Nothing running now has that id (a task id is not a running-now id).", {"reason": "not_found", "work_id": work_id})
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
    return err(rid, ERR_CONFLICT, "What is running could not be stopped.",
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


# ── what is running now: the list and the peek (RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-
# RUNNING-HERMES). ``runtime.work.list`` is the BOARD's (``agent_runtime/work/rpc.py``); these two are
# ``running.``-named so the two id spaces never share a method.

_RUNNING_LIST_PARAMS = frozenset({"kind", "limit", "sort"})


@method("runtime.work.running.list", tier=TIER_CONSOLE)
def runtime_work_running_list(rid, params, context=None):
    """What is running now (argv twin ``harness work list``): params ``kind``, ``limit`` (a positive int),
    ``sort`` (all optional) -> the argv verb's JSON envelope, verbatim — ``{schema_version, kind: "list",
    item_kind: "running_work", count, items, cursor, truncated, sources, counts, completeness}`` plus
    ``ambient`` when published (``running_work.surface.running_work_listing``, one builder). Refusal:
    ``invalid_request`` (+ ``supported`` for an unknown kind). Read off the running Hermes, so its own
    in-process lanes are counted from where they run."""
    from agent_runtime.running_work.surface import UnknownWorkKind, running_work_listing

    if not isinstance(params, dict) or not set(params) <= _RUNNING_LIST_PARAMS:
        return err(rid, ERR_INVALID_PARAMS, "Only kind, limit and sort are accepted.", {"reason": "invalid_request"})
    kind, limit, sort = params.get("kind"), params.get("limit"), params.get("sort")
    if (kind is not None and not isinstance(kind, str)) or (sort is not None and not isinstance(sort, str)) or (
            limit is not None and (type(limit) is not int or limit < 1)):
        return err(rid, ERR_INVALID_PARAMS, "kind and sort are text; limit is a positive whole number.",
                   {"reason": "invalid_request"})
    try:
        # MUTATION: drop ``limit=limit`` and test_the_list_cuts_at_its_limit reddens.
        return ok(rid, running_work_listing(kind=kind or "", limit=limit, sort=sort))
    except UnknownWorkKind as exc:
        return err(rid, ERR_INVALID_PARAMS, str(exc), {"reason": "invalid_request", "supported": exc.supported})


@method("runtime.work.running.peek", tier=TIER_CONSOLE)
def runtime_work_running_peek(rid, params, context=None):
    """A bounded read-only look at one running thing (argv twin ``harness work peek``): exactly
    ``work_id`` -> ``running_work.peek_work``'s payload (``work_id``, ``work_kind``, ``found: true``,
    ``row``, ``tail_available``, ``tail``, ``tail_limit``, ``consumed: false``, ``tail_reason``).
    Consumes nothing. Refusals: ``invalid_request`` (no id, or a malformed one), ``not_found``. On the
    running Hermes the in-process output buffers are its own, so a tail the cold child could not read is
    available here."""
    from agent_runtime.running_work import peek_work

    work_id = params.get("work_id") if isinstance(params, dict) else None
    if set(params or {}) != {"work_id"} or not isinstance(work_id, str) or not work_id.strip():
        return err(rid, ERR_INVALID_PARAMS, "work_id is required.", {"reason": "invalid_request"})
    payload = peek_work(work_id.strip())
    if payload.get("found"):
        return ok(rid, payload)
    if payload.get("error") == "malformed_work_id":
        return err(rid, ERR_INVALID_PARAMS, "That is not a running-now id.",
                   {"reason": "invalid_request", "work_id": payload.get("work_id")})
    return err(rid, ERR_NOT_FOUND, "Nothing running now has that id (a task id is not a running-now id).",
               {"reason": "not_found", "work_id": payload.get("work_id")})
