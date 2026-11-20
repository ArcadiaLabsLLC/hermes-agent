"""Whether a reply stopped short, and why: the one typed cut-off fact a chat turn carries.

Row ``RT-FU-A-REPLY-HERMES-STOPPED-AT-ITS-CONTINUATION-LIMIT-IS-MARKED-CUT-OFF-ON-ITS-TURN`` (review
w1118a.66 D2; from Eternia ``MC-FU-A-REPLY-CUT-OFF-AFTER-ITS-CONTINUATIONS-SAYS-NOTHING-OF-IT``). Seen live
2026-11-20 (Eternia lane w1118a-qafu11, model fixture ``[[qa:cut_off …]]``): a reply the model kept cutting
at its output limit was continued three times, and hermes ended the turn with the four parts stitched,
drawn as an ordinary finished reply.

Upstream's ``agent/turn_truncation.py::_continue_text`` ends such a turn through ``end_turn`` with the
stitched partial as ``final_response``, ``partial: True``, ``failure_reason: "truncated"`` and the error
:data:`CONTINUATION_LIMIT_ERROR` — and no words in the reply. The other two "truncated" exits already say
so in their reply (the window-filled exit appends a notice; a cut tool call answers with the cut-off copy),
so they carry no field: this module names only the cut-off the reply itself does not tell.

hermes owns the fact; a client renders it, never re-derives it from ``finish_reason`` or prose. The field
rides the turn's terminal frame, its journal record (``mission_chat_turns.records``) and the agent's reply
row in the history on reload (``persona_chat_history.curation``, ``operator_channels.history_messages``),
absent on every reply that was not cut off. Eternia's mirror: ``tests/fixtures/reply_cut_off_v1.json``.
"""

from __future__ import annotations

from typing import Any, Optional

__layer__ = "models"

__all__ = [
    "CONTINUATION_LIMIT_ERROR",
    "CUT_OFF_CAUSES",
    "CUT_OFF_CONTINUATION_LIMIT",
    "CUT_OFF_KEY",
    "reply_cut_off",
    "safe_cut_off",
]

#: The key on the terminal frame, the journal record and the history reply row.
CUT_OFF_KEY = "cut_off"
#: The model kept cutting its reply at its output limit and hermes stopped continuing it.
CUT_OFF_CONTINUATION_LIMIT = "continuation_limit"
#: Every cause the field can name (one today).
CUT_OFF_CAUSES = (CUT_OFF_CONTINUATION_LIMIT,)

#: Upstream's error for the continuation-limit exit (``turn_truncation._continue_text``), read, never
#: written: its stamp is ``failure_reason: "truncated"``, shared with the exits whose reply says so.
#: ``test_reply_cut_off`` drives the real loop, so an upstream rewording reds there.
CONTINUATION_LIMIT_ERROR = "Response remained truncated after 4 continuation attempts"


def reply_cut_off(raw: Any) -> Optional[str]:
    """The cut-off cause of a run's result (``run_conversation``'s dict), else None."""

    if not isinstance(raw, dict) or raw.get("partial") is not True:
        return None
    # MUTATION: drop the error match and the window-filled exit is marked too (its control reds).
    if raw.get("failure_reason") == "truncated" and raw.get("error") == CONTINUATION_LIMIT_ERROR:
        return CUT_OFF_CONTINUATION_LIMIT
    return None


def safe_cut_off(value: Any) -> Optional[str]:
    """*value* when it is a known cause, else None: what a store or a projection keeps."""

    return value if isinstance(value, str) and value in CUT_OFF_CAUSES else None
