"""Agent-chat dispatch payload fields: order scrubbing, dispatch ids, the result
envelope and the thread/reply fields.
"""

from __future__ import annotations

import json
from typing import Any
import re

from agent_runtime.profile_runner.operator_redaction import _line_has_secret

__layer__ = "stores"

__all__ = [
    "_DISPATCH_ID_RE",
    "_DISPATCH_ORDER_MAX",
    "_DISPATCH_REPLY_MAX",
    "_DISPATCH_TARGET_MAX",
    "_agent_chat_dispatch_fields",
    "_agent_chat_dispatch_reply_fields",
    "_agent_chat_dispatch_thread_fields",
    "_agent_chat_target_label",
    "_dispatch_result_envelope",
    "_safe_dispatch_id",
    "_scrub_dispatch_order",
]


def _agent_chat_target_label(tool_name: str | None, invocation: Any) -> str | None:
    """Operator label for an agent-to-agent relay: who was messaged plus a
    bounded excerpt of the briefing. Secret-bearing text is dropped whole —
    the relay stays legible, never leaky."""

    if tool_name != "agent_chat_send" or not isinstance(invocation, dict):
        return None
    persona = str(invocation.get("persona_id") or "").strip()
    if not persona or _line_has_secret(persona):
        return None
    excerpt = " ".join(str(invocation.get("message") or "").split())
    if excerpt and _line_has_secret(excerpt):
        excerpt = ""
    if len(excerpt) > 90:
        excerpt = excerpt[:89] + "…"
    return f"→ {persona}: {excerpt}" if excerpt else f"→ {persona}"


_DISPATCH_TARGET_MAX = 120


_DISPATCH_ORDER_MAX = 1500


#: The teammate's REPLY on a waiting relay. Same block grade and same bound as
#: the order — the two halves of one exchange are priced identically so neither
#: side of the operator's bubble reads as the authoritative one.
_DISPATCH_REPLY_MAX = 1500


def _scrub_dispatch_order(message: Any, *, limit: int = _DISPATCH_ORDER_MAX) -> str | None:
    """The FULL relay order for the operator console's dispatch tile: per-line
    secret drop (any line matching :func:`_line_has_secret` is removed, the rest
    kept), newlines PRESERVED (never whitespace-collapsed like ``target_label``),
    capped at ``limit`` chars with a trailing ellipsis.

    ``limit`` exists so the relay's REPLY half can reuse this exact scrub grade
    (block, newline-preserving, per-line secret drop) under its own bound; both
    dispatch-order call sites keep the default.
    """

    text = str(message or "").replace("\r\n", "\n").replace("\r", "\n")
    kept = [line for line in text.split("\n") if not _line_has_secret(line)]
    order = "\n".join(kept).strip()
    if not order:
        return None
    if len(order) > limit:
        order = f"{order[: limit - 1]}…"
    return order


def _agent_chat_dispatch_fields(tool_name: str | None, invocation: Any) -> dict[str, str]:
    """Structured dispatch fields for an ``agent_chat_send`` relay so the
    operator console renders a first-class ``→ target`` chip and the FULL order
    without re-parsing the prose ``target_label`` (which excerpts to 90 chars).
    ``target_label``/``summary`` prose stay byte-identical — these are additive
    keys alongside them. Consistent with :func:`_agent_chat_target_label`: when
    the persona carries a secret, both the label and these fields drop it."""

    if tool_name != "agent_chat_send" or not isinstance(invocation, dict):
        return {}
    fields: dict[str, str] = {}
    persona = str(invocation.get("persona_id") or "").strip()
    if persona and not _line_has_secret(persona):
        fields["dispatch_target"] = persona[:_DISPATCH_TARGET_MAX]
    order = _scrub_dispatch_order(invocation.get("message"))
    if order:
        fields["dispatch_order"] = order
    return fields


#: Opaque runtime identifiers (``persona_chat_personainst_dev_bbbbbbbbbbbb``,
#: ``personainst_dev_3ebfce41``). Deliberately NOT run through
#: :func:`_looks_sensitive_or_pathish` — that helper's path heuristic would also
#: have to be taught these shapes; the strict charset below is the whole guard,
#: plus the secret-marker check, so an id containing e.g. ``token`` is dropped.
_DISPATCH_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,240}")


def _safe_dispatch_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or _line_has_secret(text) or not _DISPATCH_ID_RE.fullmatch(text):
        return None
    return text


def _dispatch_result_envelope(result: Any) -> dict[str, Any] | None:
    """The ``agent_chat_send`` result as a mapping.

    Both shapes are the SAME envelope: the tool returns ``json.dumps(...)``, so a
    live relay reaches the progress adapter as a serialized string, while
    in-process callers hand over the dict. :func:`_is_error_result` already reads
    both for exactly this reason — this is the same pair of doors, not a new one.
    """

    if isinstance(result, dict):
        return result
    if not isinstance(result, str):
        return None
    text = result.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _agent_chat_dispatch_thread_fields(tool_name: str | None, result: Any) -> dict[str, str]:
    """The relay's OTHER HALF: which thread the message actually landed in.

    ``dispatch_target``/``dispatch_order`` name WHO was told WHAT; these name
    WHERE, so the operator console can open that thread instead of only reading
    about it. Sourced from the tool RESULT because the target thread is resolved
    downstream of the invocation — the sender may not have named a session at
    all, and the default lane mints a fresh one per dispatch.

    Only the WAITING lane can answer this. A ``wait=false`` dispatch returns
    ``"session_id": None`` by construction (the child turn resolves its thread
    long after the sender's turn ended, and the durable dispatch row learns it at
    completion), so a detached relay emits NO thread field and any console link
    stays inert. Absent stays absent: an empty string would be a link to nowhere.
    A refused relay (``ok: false``) has no thread either.

    THE THREAD ONLY, never the target's ``persona_instance_id``. The instance id
    is a mutable, re-stamped binding pointer, and naming it in an open request is
    what broke launcher chat switching on 2026-07-24 — a wire field whose only
    plausible consumer is the harmful one is not worth emitting.
    """

    if tool_name != "agent_chat_send":
        return {}
    payload = _dispatch_result_envelope(result)
    if not payload or payload.get("ok") is False:
        return {}
    # `chat_session_id` and `session_id` are the same root chat session on the
    # relay payload; the chat-scoped name is preferred so the field keeps its
    # meaning if the generic one ever narrows.
    session_id = _safe_dispatch_id(payload.get("chat_session_id") or payload.get("session_id"))
    return {"dispatch_target_session_id": session_id} if session_id else {}


def _agent_chat_dispatch_reply_fields(tool_name: str | None, result: Any) -> dict[str, str]:
    """The relay's ANSWER: what the teammate actually said back, and who said it.

    ``dispatch_target``/``dispatch_order`` name WHO was told WHAT and
    ``dispatch_target_session_id`` names WHERE — this names the reply itself, so
    the operator reads a teammate's answer in the feed instead of hunting it
    inside a collapsed result blob.

    WAITING LANE ONLY, by construction rather than by flag: a ``wait=false``
    dispatch's result payload has no ``reply`` key at all (it returns
    ``{ok, dispatched, dispatch_id, ...}``), so the detached lane exits at the
    empty-reply guard and the background delivery block stays the sole carrier
    of that reply. A refused relay (``ok: false``) has no reply either.

    ``dispatch_reply_from`` is the replying agent's operator-facing display name
    and is a NICETY: the name resolution is wrapped whole because a trace fact
    must never be lost to a naming failure. When the name cannot be resolved the
    field is absent and the console falls back to the id tier — the same ladder
    :mod:`agent_runtime.dispatch_delivery` uses for the background delivery
    block. Empty means "I could not name it", never "it has no name": a missing
    name must render an id, never an invented one.
    """

    if tool_name != "agent_chat_send":
        return {}
    payload = _dispatch_result_envelope(result)
    if not payload or payload.get("ok") is False:
        return {}
    reply = _scrub_dispatch_order(payload.get("reply"), limit=_DISPATCH_REPLY_MAX)
    if not reply:
        return {}
    fields: dict[str, str] = {"dispatch_reply": reply}
    try:
        from ..persona_assignments import persona_instance_display_name

        name = persona_instance_display_name(payload.get("persona_instance_id"))
        if name:
            fields["dispatch_reply_from"] = name[:_DISPATCH_TARGET_MAX]
    except Exception:
        pass
    return fields
