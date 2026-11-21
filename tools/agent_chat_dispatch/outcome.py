"""What a dispatched turn's outcome becomes on its row: the one payload mapping, the lane rewrites, the peer frame payload reader.

The local leg runs the turn natively (``native.py``) and hands its payload dict straight here; the
cross-install leg (``remote.py``) reads the far install's payload out of its stdout frames with
:func:`parse_reply_payload` first. Until 2026-11-21 this module was ``child.py`` and also built the
local child process (its argv, environment, pumps, group and kill); that leg retired with row
``RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES``.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

__layer__ = "policy"


#: How long a turn gets to honour its own budget before its supervisor stops waiting for it to end by
#: itself. The turn enforces the budget itself and settles gracefully (``budget_exhausted``); this is
#: the backstop for one that cannot — wedged in a syscall, stuck inside a tool that ignores its
#: interrupt — and it is generous on purpose, because stopping a turn that was about to write its
#: result loses the result.
KILL_GRACE_SECONDS = 120.0

#: The ``event`` a serve request's STDOUT lines carry
#: (``serve.py:1784``: ``_LineFrameProxy(frames, "line")``). Not ``"stdout"`` —
#: only the error stream is named after itself — and named here because a
#: reader that guesses collects nothing and sees an empty payload rather than an
#: error. Fenced by ``test_gateway_peer_cross_install_chat_e2e``, which is the
#: thing that caught the guess.
SERVE_STDOUT_EVENT = "line"


#: The key every mission-chat payload carries, on every exit path — success,
#: refusal, blocker, replay. It is what tells the handler's payload apart from
#: any other JSON object a turn's output happens to carry.
_PAYLOAD_MARKER = "capability_id"


def parse_reply_payload(text: str) -> dict[str, Any] | None:
    """The handler's payload in a turn's printed output (a peer's stdout frames), or None.

    ``emit_json`` writes indented multi-line JSON, so this cannot be a line
    scan, and a turn's stdout legitimately carries other lines (a SQLite WAL
    advisory, provider warnings) both before and after the payload. Decoding
    with ``raw_decode`` from every ``{`` and keeping the last success is the only
    shape that survives noise on both sides.
    """

    if not text:
        return None
    decoder = json.JSONDecoder()
    marked: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    index = text.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(value, dict):
            # PREFER the handler's own payload. "last object wins" was wrong in
            # both directions and neither was theoretical: a shutdown notice
            # (``{"event":"mcp_shutdown","ok":false}``) printed after a
            # successful turn made it an error, and a trailing ``{}`` made it a
            # success with an EMPTY reply — which reads as "they had nothing to
            # report". Every mission-chat payload carries ``capability_id`` on
            # every exit path, so the discriminator is the producer's own, not a
            # guess about ordering.
            if _PAYLOAD_MARKER in value:
                marked = value
            elif marked is None:
                fallback = value
        index = text.find("{", max(end, index + 1))
    # The fallback keeps a pre-marker or hand-stubbed payload readable rather
    # than reporting a turn that did answer as having produced nothing.
    #
    # It is NOT an inversion of the old "last object wins", though it reads like
    # one: `fallback` is overwritten by every unmarked object while `marked` is
    # still None, so when NO marked payload exists at all — the only case where
    # `fallback` is ever returned — it holds the last object, exactly as before.
    # The `elif` only stops it tracking objects printed AFTER a marked payload,
    # and in that case `marked` wins regardless. Stated here because the shape
    # invites the wrong reading twice over.
    return marked if marked is not None else fallback


def payload_completion(payload: dict[str, Any], returncode: int | None) -> dict[str, Any]:
    """``record_completion``'s fields for a dispatched turn's reply payload — THE one mapping.

    Read by the local supervisor (``local._record_local_outcome``) for the payload the native turn
    handed back. ``returncode`` is the handler's exit code, or ``None`` when it is not known: the
    payload's own ``ok`` decides then.
    """

    from agent_runtime.dispatch_store.models import STATE_COMPLETED, STATE_ERROR
    from agent_runtime.turn_visibility import TurnVisibility

    ok = bool(payload.get("ok")) and returncode in (0, None)
    return {
        "state": STATE_COMPLETED if ok else STATE_ERROR,
        "reply": str(payload.get("reply") or ""),
        "error": "" if ok else _detached_error_text(payload),
        "target_session_id": str(payload.get("session_id") or payload.get("chat_session_id") or ""),
        "total_tokens": payload.get("total_tokens"),
        # Read, never re-derived: `agent_runtime.turn_visibility` owns the verdict.
        "visibility": TurnVisibility.from_payload(payload).as_dict(),
        # The teammate's clarify question and its token, or the delivery hands
        # the asking agent a question it has no token to answer on.
        "clarify_request": payload.get("clarify_request"),
        # The turn's typed refusal (``chat_busy``: the target stayed busy for the
        # whole wait, so the message never ran) — the delivery reads it, never the
        # rewrite's words (RT-DELIVERY-BLOCK-SAYS-A-MESSAGE-NEVER-RAN-AS-A-TYPED-FIELD).
        "error_kind": "" if ok else str(payload.get("error_kind") or ""),
    }


def _detached_error_text(payload: dict[str, Any]) -> str:
    """The refusal text, rewritten for the lane it will actually be READ on.

    Typed refusals from the handler are written for a caller who is BLOCKED on
    the reply — ``relay_budget_exhausted`` ends "Answer your caller with what you
    have", which is sound advice mid-turn and nonsense inside a delivered error
    turn that arrives minutes later, addressed to an agent who has already moved
    on and has no caller waiting.

    Only the ones whose guidance is lane-specific are rewritten; everything else
    passes through verbatim, because a refusal an agent can act on is worth more
    than a uniformly-phrased one it cannot.
    """

    kind = str(payload.get("error_kind") or "")
    raw = str(payload.get("error") or payload.get("blocker") or "the dispatched turn failed")
    rewrite = _LANE_REWRITES.get(kind)
    return rewrite.format(kind=kind) if rewrite is not None else raw[:600]


_RELAY_BUDGET_REWRITE = (
    "The dispatch was refused before it ran: the relay chain it belongs to had no wall "
    "budget left. Nothing was executed and there is no partial result. Re-dispatch it as "
    "a fresh request if you still need it."
)
_RELAY_REACH_REWRITE = (
    "The dispatch was refused before it ran ({kind}): this request would have looped back "
    "through an agent already on the relay chain, or gone deeper than the chain allows. "
    "Nothing was executed. Ask the agent directly, or do it yourself."
)

_BUSY_TARGET_REWRITE = (
    "Not delivered: they were still busy with another turn for the whole time this waited, "
    "so this message never ran and they have not seen it. If that turn is work you sent them, "
    "stop it with agent_chat_dispatches(cancel=\"<its dispatch_id>\") and send this again; "
    "otherwise send it again once they are free."
)

#: The refusals whose guidance is lane-specific, by ``error_kind`` (rule 12).
#: The relay kinds are ``agent_runtime.relay_policy``'s (recorded in
#: ``mission_chat_outcome.DELEGATED_ERROR_KIND_SOURCES``); named here, their one
#: reader, rather than minted as an Enum — they ride every chat payload as
#: strings. ``chat_busy`` is ``ChatErrorKind.CHAT_BUSY``'s value. Every other kind
#: passes through verbatim.
_LANE_REWRITES: Mapping[str, str] = {
    "relay_budget_exhausted": _RELAY_BUDGET_REWRITE,
    "relay_cycle": _RELAY_REACH_REWRITE,
    "relay_depth_limit": _RELAY_REACH_REWRITE,
    # The supervisor waits out a busy target (``local._wait_for_busy_target``); this is
    # read only when the target was still busy at the end of the dispatch's waiting time.
    "chat_busy": _BUSY_TARGET_REWRITE,
}
