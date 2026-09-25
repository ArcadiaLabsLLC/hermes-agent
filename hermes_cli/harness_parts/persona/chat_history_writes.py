"""The ONE write path for a persona chat row: redaction, operator/assistant appends, mirror, token counts.

Separate because every chat message persists through ``_persist_persona_chat_row``
(rule 13: one write path per state).
"""

from __future__ import annotations

import os
import re
from agent_runtime.serde import positive_int
from agent_runtime.persona_assignments import (
    PERSONA_INSTANCE_ID_PREFIX,
    chat_session_owner_instance_id,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_durability import (
    persona_chat_persistence_failed as _persona_chat_persistence_failed,
)
from .chat_session import _persona_chat_native_history, _persona_chat_native_tip

__layer__ = "stores"
__all__ = [
    "PERSONA_CHAT_OPERATOR_MESSAGE_LIMIT",
    "PERSONA_CHAT_REPLY_LIMIT",
    "_chat_turn_tool_names",
    "_mirror_persona_chat_message",
    "_persona_chat_existing_turn",
    "_persona_chat_fault_injection",
    "_redact_persona_chat_text",
    "_resolve_relay_sender_marker",
]


def _persona_chat_fault_injection(boundary: str) -> None:
    """Named live-proof seam; inert unless the exact boundary is requested."""

    requested = str(os.environ.get("HERMES_PERSONA_CHAT_FAULT_INJECTION", "")).strip()
    if requested == boundary:
        raise RuntimeError(f"injected persona chat fault at {boundary}")


_PERSONA_CHAT_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|bearer)\s*[:=]\s*\S+"
)


# One pair of caps for the whole mission-chat lane. The reply cap matches the
# operator-channel projection read cap (operator_channels._safe_conversation_text
# limit=20000) so a persisted reply is never shorter than what the projection
# is willing to display.
PERSONA_CHAT_OPERATOR_MESSAGE_LIMIT = 12000


PERSONA_CHAT_REPLY_LIMIT = 20000


def _redact_persona_chat_text(value, *, limit: int) -> str:
    safe = _safe_persona_chat_body_text(value, limit=limit)
    if not safe:
        return ""
    return _PERSONA_CHAT_SECRET_RE.sub(r"\1: [redacted]", safe)


def _safe_persona_chat_body_text(value, *, limit: int) -> str:
    text = str(value or "").replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Preserve intra-line whitespace: chat bodies carry code blocks and aligned
    # output, and collapsing runs of spaces destroys them irreversibly at
    # persistence time. Only trim line endings and cap blank runs.
    lines = [line.rstrip() for line in text.split("\n")]
    normalized = "\n".join(lines).strip()
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    if len(normalized) > limit:
        # Truncation must be visible, never silent.
        normalized = normalized[:limit].rstrip() + " … [truncated]"
    return normalized


def _chat_turn_tool_names(elements) -> list[str]:
    """Tool names this turn actually ran, in emitter order.

    Feeds the synthesized budget-exhausted summary: when not even the final
    checkpoint call fits, the operator still gets an honest account of what DID
    execute instead of a blank blocked turn.
    """

    names: list[str] = []
    for element in elements or ():
        if not isinstance(element, dict) or element.get("kind") != "tool":
            continue
        name = safe_assignment_token(element.get("name"))
        if name:
            names.append(name)
    return names


def _persona_chat_existing_turn(
    *,
    session_db,
    session_id: str | None,
    client_message_id: str | None,
) -> dict[str, object]:
    if session_db is None or not session_id or not client_message_id:
        return {}
    try:
        active_session_id = _persona_chat_native_tip(session_db, session_id)
        messages = _persona_chat_native_history(session_db, active_session_id)
    except Exception:
        return {}

    result: dict[str, object] = {}
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        message_id = safe_assignment_text(
            item.get("platform_message_id") or item.get("message_id"), limit=200
        )
        if message_id != client_message_id and not message_id.startswith(
            f"{client_message_id}:"
        ):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "user" and "operator" not in result:
            result["operator"] = item
        elif role == "assistant":
            result["assistant"] = item
    return result


def _resolve_relay_sender_marker(
    requested_by,
    *,
    instance_store,
    relay_chain_in,
) -> str | None:
    """Resolve an incoming message's ORIGIN into a finish_reason marker.

    This is the one site that decides what the persisted user row is typed
    with, so both non-operator origins resolve here rather than in two places
    that could disagree about the same column:

    * ``requested_by = "harness-delivery:<dispatch>:<flag>"`` — a dispatch
      delivery the harness forged into the sender's own thread. Checked FIRST
      because it is an exact-prefix machine provenance, and because a delivery
      is not a relay: no agent sent it and there is no sending persona to name.
    * ``requested_by = "agent:<caller session id>"`` — an ``agent_chat_send``
      relay (set by tools/agent_chat_tool.py from the CALLER's session).
      Resolution is tiered most-to-least specific; each tier is a deliberate
      source of truth and the bare ``relay_from::`` marker is the honest
      unknown, never a guessed operator.

    Operator / CLI / coordinator sends match neither, and must persist
    byte-identically to today (this returns ``None`` for them → no marker).

    The name is kept for the AST gate that pins ``_cmd_mission_chat_message``
    to this single call site.
    """
    from agent_runtime import dispatch_delivery as _dispatch_delivery
    from agent_runtime import relay_policy as _relay_policy

    delivery = _dispatch_delivery.parse_delivery_requested_by(requested_by)
    if delivery is not None:
        return _relay_policy.build_harness_delivery_marker(
            delivery.dispatch_id, delivery.notify_operator, delivery.state
        )
    if not isinstance(requested_by, str) or not requested_by.startswith("agent:"):
        return None
    token = requested_by[len("agent:"):].strip()
    if not token:
        return None

    from agent_runtime import relay_policy

    persona_id: str | None = None
    instance_id: str | None = None
    instances = instance_store.list_all()
    by_id = {instance.id: instance for instance in instances}

    # Tier 1 — the caller session is a minted chat session; its exact-mint owner
    # is the sending instance (sibling-safe: personainst_<p>_agent_2 survives).
    # Resolve the persona from the store row, never by string-parsing the
    # instance id (placement suffixes make that fragile).
    owner = chat_session_owner_instance_id(token)
    if owner and owner in by_id:
        instance_id = owner
        persona_id = safe_assignment_token(by_id[owner].persona_id) or None
    elif owner and owner.startswith(PERSONA_INSTANCE_ID_PREFIX):
        # A real instance handle whose row is absent from this snapshot (e.g.
        # reaped): keep the instance identity, leave the persona honestly
        # unknown rather than guessing.
        instance_id = owner

    # Tier 2 — task-lane callers: the caller session is the instance's bound
    # session, not a chat-shaped id. S56 removed the ``active_worker_session_id``
    # candidate with the worker store that was its only writer.
    if instance_id is None and persona_id is None:
        for instance in instances:
            candidates = {
                safe_assignment_text(instance.default_chat_session_id, limit=200),
            }
            if token in candidates:
                instance_id = instance.id
                persona_id = safe_assignment_token(instance.persona_id) or None
                break

    # Tier 3 — persona-level fallback: the immediate caller is the LAST entry of
    # the pre-target-append relay chain (canonical persona id; no instance).
    if instance_id is None and persona_id is None and relay_chain_in:
        persona_id = relay_chain_in[-1] or None

    # Tier 4 — nothing resolved → the honest bare marker relay_from::.
    return relay_policy.build_relay_sender_marker(persona_id, instance_id)


def _append_persona_operator_turn(
    *,
    session_db,
    session_id: str,
    message: str,
    client_message_id: str | None = None,
    skip_if_present: bool = False,
    relay_marker: str | None = None,
    required: bool = False,
) -> bool:
    if session_db is None or not session_id:
        return _persona_chat_persistence_failed(
            "operator_append", None, required=required
        )
    if skip_if_present:
        return True
    safe_message = _redact_persona_chat_text(message, limit=PERSONA_CHAT_OPERATOR_MESSAGE_LIMIT)
    if not safe_message:
        return True
    return _persist_persona_chat_row(
        session_db=session_db,
        session_id=session_id,
        role="user",
        text=safe_message,
        client_message_id=safe_assignment_text(client_message_id, limit=200) or None,
        # Relayed incoming rows carry the sending agent's identity here (the
        # pre_trace_ack typed-marker-in-finish_reason precedent); operator/CLI
        # sends pass relay_marker=None → finish_reason stays None, unchanged.
        relay_marker=relay_marker,
        step="operator_append",
        required=required,
    )


def _append_persona_assistant_text(
    *,
    session_db,
    session_id: str,
    text: str,
    client_message_id: str | None = None,
    required: bool = False,
) -> bool:
    # C8: the ONLY assistant rows this writes are real recorded replies. The
    # pre-trace ack lane that used to inject a canned assistant row here (with
    # a finish_reason marker the projections then had to suppress) is retired —
    # acks are a presentation-only `turn.ack` v2 stream frame now (see
    # _ChatProtocolV2Emitter.ack). Pre-C8 ack rows persisted before this change
    # stay in SessionDB (archive-never-delete) and keep their typed kind on the
    # read side.
    if session_db is None or not session_id:
        return _persona_chat_persistence_failed(
            "assistant_append", None, required=required
        )
    safe = _redact_persona_chat_text(text, limit=PERSONA_CHAT_REPLY_LIMIT)
    if not safe:
        return True
    safe_client_message_id = safe_assignment_text(client_message_id, limit=200)
    if _persona_chat_existing_turn(
        session_db=session_db,
        session_id=session_id,
        client_message_id=safe_client_message_id,
    ).get("assistant"):
        return True
    return _persist_persona_chat_row(
        session_db=session_db,
        session_id=session_id,
        role="assistant",
        text=safe,
        client_message_id=safe_client_message_id or None,
        step="assistant_append",
        required=required,
    )


def _persist_persona_chat_row(
    *,
    session_db,
    session_id: str,
    role: str,
    text: str,
    client_message_id: str | None,
    step: str,
    required: bool,
    relay_marker: str | None = None,
) -> bool:
    """THE explicit-append seam for persona-chat rows.

    Both ``_append_persona_operator_turn`` and ``_append_persona_assistant_text``
    funnel their ``session_db.append_message`` through here, and the write is
    wrapped in ``mirrored_persona_chat_append`` so the SessionDB row and its
    live-log line can never drift apart — one write, one mirror, no hook
    copy-pasted per call site.

    The mirror is bound by a CONTEXT MANAGER rather than by a trailing call on
    purpose. The first cut hooked append sites by convention and immediately
    missed one (``agent_runtime.continuity.return_summary_to_parent_session``,
    the child return-summary lane), so its rows never reached the live log. A
    seam a new append site has to *wrap* is the version of that rule a reviewer
    can actually check.

    The mission-chat lane does not come through here: since native session
    continuity landed it no longer appends the operator/assistant rows itself
    (the runtime persists them with the turn — see
    ``profile_runner.stage_persona_chat_user_row_marker``), so it mirrors from
    its own two known points via ``_mirror_persona_chat_message``.

    KEPT DELIBERATELY — do not re-propose this as dead code
    -------------------------------------------------------
    The 2026-08-18 dead-code audit (NEW-1) proposed reaping this function and
    the two ``_append_*`` writers above it as a "test-only-alive island": zero
    production callers, ~184 lines, ~250 test lines with them. The census is
    RIGHT and the conclusion was REFUSED on 2026-08-19. Reasons, so the next
    sweep does not spend the same hours:

    * **Zero callers is a phase, not a verdict, for a chokepoint.** This is not
      an orphan that lost its lane — it is the door the lane goes through, and
      the lane is currently entering by another route (native continuity). The
      explicit-append route is still reachable and still used: the relay lane
      drives ``_append_persona_operator_turn(relay_marker=)``, whose wire
      behaviour broke silently for eleven days once already.
    * **Deleting it deletes five enforcement points, not one function.**
      Redaction with the per-role limit, the assistant-row idempotency check,
      the mirror binding, the typed ``PersonaChatPersistenceError`` reporting,
      and the ``required=`` raise-or-degrade split. The next explicit append
      would hand-roll all five — which is exactly the failure this seam's
      SHAPE already records: the first cut hooked append sites by convention
      and immediately missed one.
    * **A seam whose only current exercise is a test is under-used, not dead.**
      The honest fix is to give it an executable contract rather than to remove
      it, which is what ``tests/hermes_cli/test_persona_chat_append_seam.py``
      now does.

    The real open question is an OPERATOR one, recorded rather than answered:
    is the explicit-append lane coming back (relay / CLI sends), or should the
    persona-chat write path be declared native-only? If the latter, this goes —
    but deliberately, with its five guarantees re-homed, not as a line-count
    reap.
    """

    from agent_runtime.chat_live_log import mirrored_persona_chat_append

    try:
        with mirrored_persona_chat_append(
            session_db=session_db,
            session_id=session_id,
            role=role,
            text=text,
            client_message_id=client_message_id,
            relay_marker=relay_marker,
        ):
            session_db.append_message(
                session_id=session_id,
                role=role,
                content=text,
                finish_reason=relay_marker,
                platform_message_id=client_message_id,
            )
    except Exception as exc:
        return _persona_chat_persistence_failed(step, exc, required=required)
    return True


def _mirror_persona_chat_message(
    *,
    session_db=None,
    session_id: str,
    role: str,
    text: str,
    client_message_id: str | None = None,
    turn_id: str | None = None,
    relay_marker: str | None = None,
) -> None:
    """Mirror ONE persisted persona-chat message into the live chat log.

    The mission-chat lane's hook (the explicit-append lanes use the
    ``mirrored_persona_chat_append`` seam instead). The text handed in has
    ALREADY crossed the ``_redact_persona_chat_text`` write boundary, so the
    mirror is redaction-safe by construction; the mirror re-runs the shared
    secret rule anyway, because "the caller already did it" is exactly how a
    redaction boundary rots.

    Best effort by contract: the mirror is a regenerable convenience artifact
    (``agent_runtime/chat_live_log.py``), and a mirror failure must never take
    down a chat turn whose transcript is already durable. Failures are counted
    inside the mirror module rather than swallowed anonymously.

    Function-local import, like the rest of this file.
    """

    try:
        from agent_runtime.chat_live_log import record_chat_message

        record_chat_message(
            session_id=session_id,
            role=role,
            text=text,
            turn_id=turn_id,
            client_message_id=client_message_id,
            relay_marker=relay_marker,
            session_db=session_db,
        )
    except Exception:
        return None
    return None


def _update_persona_chat_token_counts(*, session_db, session_id: str, result) -> None:
    """Record this turn's canonical token usage onto the bound chat session —
    SCRATCH-SESSION LANES ONLY.

    Valid only where the runtime ran with an ephemeral scratch session
    (``mission_chat_reply(session_id=None)``, e.g. the assignment relay lane):
    there ``conversation_loop``'s per-call token writes land on the throwaway
    scratch row, so this explicit post-turn write is the sole writer of the
    bound session the Launcher reads.

    It must NEVER run on the native-continuity chat lane, where the runtime is
    bound to the real chat session (``session_id=active_session_id`` with
    ``persist_agent_session=True``): the per-call runtime writes already land on
    the bound row, and stacking this turn-total write on top double-counts every
    counter at exactly 2x (the 2026-07 "in 20,208 for a bare hi" Runtime-card
    bug). One lane, one usage writer.

    It forwards the COMPLETE canonical usage (cache reads/writes and reasoning,
    not just input/output). ``input_tokens`` is already the uncached, full-price
    remainder; the cache buckets are what let the Launcher tell a warm cache from
    a cold one being re-billed at full rate. Dropping them here was the reason the
    bound session always reported zero cache — keep this write canonical so no
    lossy subset can silently diverge again.
    """
    if session_db is None or not session_id or result is None:
        return
    input_tokens = positive_int(getattr(result, "input_tokens", None), default=0)
    output_tokens = positive_int(getattr(result, "output_tokens", None), default=0)
    cache_read_tokens = positive_int(getattr(result, "cache_read_tokens", None), default=0)
    cache_write_tokens = positive_int(getattr(result, "cache_write_tokens", None), default=0)
    reasoning_tokens = positive_int(getattr(result, "reasoning_tokens", None), default=0)
    api_calls = positive_int(getattr(result, "api_calls", None), default=0)
    if (
        input_tokens == 0
        and output_tokens == 0
        and cache_read_tokens == 0
        and cache_write_tokens == 0
        and reasoning_tokens == 0
        and api_calls == 0
    ):
        return
    try:
        session_db.update_token_counts(
            session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            api_call_count=api_calls,
            model=getattr(result, "model", None),
        )
    except Exception:
        return
