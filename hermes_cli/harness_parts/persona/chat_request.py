"""Mission-chat request validation and refusal payloads: model override, caller, clarify binding, retired target.

Separate because every refusal a turn can return before it runs is built here,
from the request alone plus the clarify-ticket store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from agent_runtime import paths
from agent_runtime.config import mission_chat_clarify_token_binding
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    RetiredPersonaInstanceError,
    canonical_chat_instance_id,
    safe_assignment_text,
)
from agent_runtime.persona_chat_continuity import PersonaChatClarifyTicketStore
from .chat_session import _safe_chat_model_override_value

__layer__ = "stores"
__all__ = [
    "_invalid_chat_model_override_payload",
    "_missing_chat_message_payload",
    "_mission_chat_caller_refusal",
    "_mission_chat_clarify_request_payload",
    "_mission_chat_retired_target_refusal",
    "_requested_chat_model_override",
    "_resolve_mission_chat_clarify_binding",
    "_retired_persona_instance_payload",
    "_settle_mission_chat_clarify_binding",
]


def _retired_persona_instance_payload(
    exc: RetiredPersonaInstanceError,
) -> dict[str, object]:
    return _retired_persona_instance_refusal(
        persona_instance_id=exc.persona_instance_id,
        archive_path=exc.archive_path,
        error_kind=exc.code,
    )


def _retired_persona_instance_refusal(
    *,
    persona_instance_id: str,
    archive_path: object,
    # The ONE ``error_kind`` in this file still spelled as a literal, and it is
    # structural rather than an oversight: a default argument is evaluated when
    # the ``def`` executes, and until lane H1 this file was EXEC'd into
    # harness.py's globals, where a module-level import was the namespace
    # collision the exec'd-part discipline forbade (hoisting is H3's call).
    # The value is pinned to ``ChatErrorKind.RETIRED_PERSONA_INSTANCE``
    # by tests/agent_runtime/test_mission_chat_outcome.py, so it cannot drift.
    error_kind: str = "retired_persona_instance",
) -> dict[str, object]:
    """ONE retired-target refusal body, whether or not an exception carried it.

    A pre-flight that refuses BEFORE the write lane has no exception to render,
    but the caller must not be able to tell the difference: same ``error_kind``,
    same fields, same ``next_expected``. Two spellings of this payload would be
    two contracts."""
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import ExecutionState

    return {
        "ok": False,
        "execution_state": ExecutionState.REFUSED,
        "error_kind": error_kind,
        "error": (
            f"persona instance {persona_instance_id} was retired with its "
            "placement and cannot be reopened as a live agent"
        ),
        "persona_instance_id": persona_instance_id,
        "archive_path": str(archive_path),
        "history_preserved": True,
        "next_expected": (
            "view the preserved chat history read-only, or create a fresh "
            "placement with a new instance id"
        ),
    }


def _requested_chat_model_override(args) -> dict[str, object] | None:
    use_default = bool(getattr(args, "use_agent_default", False))
    provider = _safe_chat_model_override_value(getattr(args, "provider", None), field="provider")
    model = _safe_chat_model_override_value(getattr(args, "model", None), field="model")
    if use_default and (provider or model):
        raise ValueError("use_agent_default cannot be combined with provider or model")
    if use_default:
        return {
            "schema_version": 1,
            "clear": True,
            "source": "operator",
            "scope": "mission_control_chat_session",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    if not provider and not model:
        return None
    return {
        "schema_version": 1,
        "provider": provider,
        "model": model,
        "source": "operator",
        "scope": "mission_control_chat_session",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _missing_chat_message_payload() -> dict[str, object]:
    """Refusal for a send that carries no message text.

    One spelling for two call sites: the pre-mint gate and the post-lease check
    that has always owned it."""

    return {"ok": False, "error": "message is required"}


def _invalid_chat_model_override_payload(
    exc: Exception,
    *,
    persona_id: str,
    persona_instance_id: str | None,
    session_id: str | None,
) -> dict[str, object]:
    """Refusal for a provider/model override the caller stated wrongly.

    Built here rather than inline because the same refusal is now reachable
    from TWO points of one turn — the pre-mint gate (no session exists yet, so
    the session fields are honestly null) and the post-``open_chat`` resolve —
    and one envelope with two spellings is how ``error_kind`` drifts."""
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import ChatErrorKind

    return {
        "ok": False,
        "error_kind": ChatErrorKind.INVALID_CHAT_MODEL_OVERRIDE,
        "error": safe_assignment_text(str(exc), limit=320),
        "persona_instance_id": persona_instance_id,
        "persona_id": persona_id,
        "session_id": session_id,
        "chat_session_id": session_id,
        "next_expected": "choose a valid provider/model id or clear the chat-scoped override; Hermes profile defaults were not changed",
    }


def _mission_chat_caller_refusal(
    args,
    *,
    persona_id: str,
    persona_instance_id: str | None,
) -> dict[str, object] | None:
    """The refusals decidable from the caller's arguments alone, or ``None``.

    Exists so they can run BEFORE a dispatch mints its task-scoped thread: a
    mint is durable (a titled row in Mission Control) and a repoint (the
    instance's default-thread pointer), so a send that was always going to be
    refused must not leave either behind. Both checks are pure functions of
    ``args``, so evaluating them here AND at their original sites is free and
    keeps those sites intact for the explicit-session lane."""

    if not safe_assignment_text(getattr(args, "message", None), limit=12000):
        return _missing_chat_message_payload()
    try:
        _requested_chat_model_override(args)
    except ValueError as exc:
        return _invalid_chat_model_override_payload(
            exc,
            persona_id=persona_id,
            persona_instance_id=persona_instance_id,
            session_id=None,
        )
    return None


def _clarify_ticket_store_populated() -> bool:
    """Cheap probe: has this runtime ever minted a clarify ticket?

    The tokenless settlement below (a turn landing in a session that has an open
    ticket) has to run on turns that present NO token, which is nearly all of
    them. Gating it on ``mission_chat_clarify_token_binding()`` would put an
    UNCACHED root-``config.yaml`` parse on every mission-chat turn — the exact
    cost ``resolve_dispatch_session_decision``'s lazy-config note exists to
    avoid. One ``exists()`` answers it instead: with the gate off nothing ever
    mints, so the directory never appears and no ticket work (and no config
    read) happens at all."""

    try:
        return (paths.store_root() / "persona_chat_clarify_tickets").exists()
    except OSError:  # pragma: no cover - defensive; a store probe must not fail a turn
        return False


def _resolve_mission_chat_clarify_binding(
    args, *, session_id: str | None
) -> dict[str, object] | None:
    """Resolve an echoed ``clarify_token`` into the thread it was asked in.

    Returns the turn's ``clarify_binding`` report block, or ``None`` when the
    caller presented no token (the overwhelmingly common case, and the one that
    must cost nothing — no store read, no config parse).

    **The token beats a conflicting ``session_id``, loudly.** Refusing would
    defeat the purpose: this binding exists precisely because agents are
    unreliable about session arguments, so a reply that echoes the token AND
    attaches a stale session id must still land correctly. Silence would be the
    other half of the same failure, so the override is reported in
    ``overrode_session_id``.

    **An unknown or pruned token degrades, it does not refuse.** Tickets are
    swept on a TTL; turning a GC'd ticket into a hard failure would punish a
    parent that did exactly the right thing. The turn falls through to normal
    precedence and says so (``state: "unknown_token"``)."""

    token = safe_assignment_text(getattr(args, "clarify_token", None), limit=240)
    if not token:
        return None
    if not mission_chat_clarify_token_binding():
        return None
    ticket = PersonaChatClarifyTicketStore().resolve(token)
    bound_session_id = safe_assignment_text(
        (ticket or {}).get("chat_session_id"), limit=240
    )
    if not bound_session_id:
        return {
            "token": token,
            "state": "unknown_token",
            "bound_via": "none",
            "bound_session_id": None,
            "overrode_session_id": None,
        }
    stated = safe_assignment_text(session_id, limit=200)
    return {
        "token": token,
        "state": "bound",
        "bound_via": "clarify_token",
        "bound_session_id": bound_session_id,
        "overrode_session_id": stated if stated and stated != bound_session_id else None,
    }


def _settle_mission_chat_clarify_binding(
    binding: dict[str, object] | None,
    *,
    session_id: str | None,
    client_message_id: str | None,
    explicit_session_id: str | None,
) -> dict[str, object] | None:
    """Close out this turn's clarify accounting and return the report block.

    Two settlements, one chokepoint. A turn that BOUND through a token settles
    that ticket (``bound``, or ``rebound`` when a different message answers the
    same question again). A turn that presented NO token but landed in a session
    that HAS an open ticket settles it anyway — ``bound_via: "session_id"`` when
    the caller named the thread, ``"none"`` when they merely inherited it. That
    tokenless half is not bookkeeping pedantry: without it every
    prompt-compliant parent leaves a permanently-open ticket and the adoption
    metric lies in the pessimistic direction, which is the direction that would
    argue for building more machinery than this needs.

    Called only after the turn's reply is durable — a refused turn answered
    nothing and must not mark a question answered."""

    store = PersonaChatClarifyTicketStore()
    if binding is not None:
        if binding.get("bound_via") != "clarify_token":
            return binding
        record = store.settle(
            binding.get("token"),
            client_message_id=client_message_id,
            bound_via="clarify_token",
        )
        if record is not None and record.get("state") == "rebound":
            binding = {**binding, "state": "rebound"}
        return binding
    if not _clarify_ticket_store_populated():
        return None
    ticket = store.open_ticket_for_session(session_id)
    if ticket is None:
        return None
    bound_via = "session_id" if safe_assignment_text(explicit_session_id, limit=200) else "none"
    store.settle(
        ticket.get("clarify_token"),
        client_message_id=client_message_id,
        bound_via=bound_via,
    )
    return {
        "token": safe_assignment_text(ticket.get("clarify_token"), limit=240) or None,
        "state": "answered",
        "bound_via": bound_via,
        "bound_session_id": safe_assignment_text(ticket.get("chat_session_id"), limit=240)
        or None,
        "overrode_session_id": None,
    }


def _mission_chat_clarify_request_payload(
    chat_result,
    *,
    session_id: str | None,
    persona_id: str,
    persona_instance_id: str | None,
    client_message_id: str | None,
    turn_id: str | None,
    requested_by_session: str | None,
) -> dict[str, object] | None:
    """The turn's ``clarify_request``, with a freshly minted binding token.

    The token is minted HERE — where the question is materialized into the turn
    payload — and never inside :class:`MissionChatClarifyCapture`, which is
    deliberately a pure dataclass with no store and no session id. No clarify,
    no ticket: the normal path pays nothing.

    A mint failure is not a turn failure. The question still ships (without a
    token), the answering parent falls through to today's precedence, and the
    only thing lost is the structural binding — which is exactly the state the
    lane was in before this existed."""

    raw = (getattr(chat_result, "raw", None) or {}).get("clarify_request")
    if not isinstance(raw, dict) or not raw:
        # Passed through verbatim, exactly as before this seam existed: no
        # question asked, nothing to bind.
        return raw
    if not mission_chat_clarify_token_binding():
        return dict(raw)
    token = PersonaChatClarifyTicketStore().mint(
        chat_session_id=session_id,
        persona_instance_id=persona_instance_id,
        persona_id=persona_id,
        asked_by_client_message_id=client_message_id,
        asked_turn_id=turn_id,
        requested_by_session=requested_by_session,
    )
    payload = dict(raw)
    if token:
        payload["clarify_token"] = token
    return payload


def _mission_chat_retired_target_refusal(
    instance_store: PersonaInstanceStore,
    *,
    persona_id: str,
    persona_instance_id: str | None,
) -> dict[str, object] | None:
    """Refusal when the dispatch target's placement was RETIRED, or ``None``.

    The sibling of :func:`_mission_chat_caller_refusal` for the one refusal that
    is not a function of ``args``: it needs the store. Same reason for being
    here rather than only at its original site — ``open_chat`` surfaces this
    refusal by raising, but the mint below binds through ``open_chat`` only
    AFTER creating and titling the session row, so a dispatch to a target that
    can never be served used to leave a permanent empty thread behind (and
    escape as an untyped traceback, because this call site's typed handler
    wraps the LATER bind, not the mint).

    Read-only: the store predicate never writes, and a store that cannot answer
    returns ``None`` rather than fabricating a refusal — the mint lane and
    ``open_chat`` both still refuse a retired target, so failing open here costs
    the litter, never the guarantee."""

    try:
        archive_path = instance_store.retired_instance_archive_path(
            persona_instance_id, persona_id=persona_id
        )
    except Exception:
        return None
    if archive_path is None:
        return None
    return _retired_persona_instance_refusal(
        persona_instance_id=canonical_chat_instance_id(persona_id, persona_instance_id),
        archive_path=archive_path,
    )
