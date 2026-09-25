"""Identity answers that READ the roster: a chat session's owner persona, an
instance's display name, the sender-scope workspace, an instance's default chat
session, and persona comparison
(which resolves instance ids through the store).

Separate from ``identity`` because these construct a ``PersonaInstanceStore``;
``identity`` stays a leaf the store itself imports.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_runtime.persona_assignments.identity import (
    _PERSONA_CHAT_SESSION_PREFIX,
    canonical_chat_instance_id,
    chat_session_is_foreign_to_instance,
    chat_session_owner_instance_id,
    normalize_persona_id,
)
from agent_runtime.persona_assignments.store import PersonaInstanceStore
from agent_runtime.persona_assignments.tokens import (
    safe_assignment_text,
    safe_assignment_token,
)

__layer__ = "stores"

__all__ = [
    "chat_session_owner_persona",
    "normalize_persona_or_template_id",
    "persona_id_from_instance_id",
    "persona_instance_display_name",
    "personas_equal",
    "resolve_default_chat_session_id_for_instance",
    "sender_scope_workspace_id",
    "_persona_comparison_key",
]


def chat_session_owner_persona(session_id: str | None) -> tuple[str, str] | None:
    """``(persona_id, persona_instance_id)`` that owns a chat root, or ``None``.

    THE answer to "whose work is this" for anything that knows only a chat
    session id. One authority on purpose: the composition below —
    session → owning instance id → that instance's ``persona_id`` — used to be
    open-coded inside ``dispatch_delivery._sender_persona``, and the running-work
    projection then shipped ``owner: {persona_id: null, ...}`` on every
    delegation row rather than reach for it, which made an entire kind of work
    invisible on the operator's Activity surface. Both call sites now resolve
    here, so a delegation and a delivered dispatch can never disagree about who
    owns a thread.

    Absence is a real answer and is never softened: a session with no derivable
    owner, or an owner the instance store does not have, returns ``None``. The
    positive-ownership rule the delivery lane depends on (#64484) is exactly this
    — "no instance" means "do not deliver", never "deliver anyway" — and the
    projection's rule is its twin: an unresolved owner must be REPORTED unowned,
    never invented.

    Pure read: it opens no store it would have to create and writes nothing, so
    a read-only projection may call it.
    """

    try:
        instance_id = chat_session_owner_instance_id(session_id)
    except Exception:
        return None
    if not instance_id:
        return None
    try:
        instance = PersonaInstanceStore().get(instance_id)
    except Exception:
        return None
    persona_id = str(getattr(instance, "persona_id", "") or "")
    if not persona_id:
        return None
    return persona_id, instance_id


def persona_instance_display_name(persona_instance_id: Any) -> str:
    """The operator-facing NAME of an instance ("Neko Mission Lead"), or ``""``.

    THE answer to "what is this instance called" for anything that knows only an
    instance handle. It reads the same row and the same field every other naming
    surface reads — ``PersonaInstanceStore.get(...).display_name``, which is what
    ``operator_channels`` bulk-builds its ``display_names`` map out of and what
    ``persona_instance_summary`` publishes — so a delivered reply, a relayed
    message and the roster can never disagree about an agent's name.

    FAIL-SAFE BY CONSTRUCTION, and that is the whole reason it exists as a
    function rather than as three inline ``try`` blocks. Its callers are
    PRESENTATION paths: the forged delivery block (whose exceptions burn a
    delivery attempt against a cap) and the running-work projection (whose
    exceptions blank an operator's Activity lane). A name is a nicety; the
    delivery and the projection are not. So every failure — an absent row, an
    unreadable store, a home that does not hold this instance, an id that is not
    an instance handle at all — returns the empty string, and the caller falls
    back to the id it already had.

    Empty is therefore "I could not name it", never "it has no name": a caller
    must render the id rather than invent one, exactly as the relay attribution
    lane does when an instance does not resolve in the roster.

    The name comes back through :func:`safe_assignment_text` at the SAME 120-char
    bound ``operator_channels`` applies to its bulk ``display_names`` map, so a
    row carrying a novel-length name cannot widen a wire projection or a forged
    message body through this door.
    """

    handle = str(persona_instance_id or "").strip()
    if not handle:
        return ""
    try:
        instance = PersonaInstanceStore().get(handle)
    except Exception:
        # DEBUG, not WARNING: an unresolvable name is an ordinary outcome for a
        # retired instance or a cross-home read, and a delivery lane that logged
        # a warning per pass would drown the one that matters.
        logging.getLogger(__name__).debug(
            "persona_instance_display_name could not resolve instance=%s",
            handle,
            exc_info=True,
        )
        return ""
    return safe_assignment_text(getattr(instance, "display_name", None), limit=120)


def sender_scope_workspace_id(
    session_id: str | None,
    *,
    instance_store: "PersonaInstanceStore | None" = None,
    active_workspace_id: str | None = None,
) -> str | None:
    """The workspace scope a chat SENDER addresses a target from.

    The single impure derivation shared by every addressable-roster surface that
    resolves a target for a SENDER (mission-chat target guard, ``agent_chat``
    threads/open): session → the owning instance → that instance's own workspace
    pointer (falling back to the active workspace for a runtime-global sender).
    A session with no derivable owner, or no session at all (a bare operator/CLI
    invocation), scopes to the active workspace — so the resolver degrades to the
    active scene rather than hiding the whole roster.

    Pairs with the pure :mod:`agent_runtime.workspace_scope` filters: this
    answers "which workspace am I addressing FROM"; those answer "which rows are
    addressable from that workspace". ``active_workspace_id`` /
    ``instance_store`` are injectable for tests and to reuse a caller's store.
    """

    from ..workspace_scope import effective_workspace_id

    if active_workspace_id is None:
        from ..store import WorkspaceStore

        active_workspace_id = WorkspaceStore().active_id()
    scope_workspace_id = active_workspace_id
    sender_session = safe_assignment_text(session_id, limit=200)
    if not sender_session:
        return scope_workspace_id
    sender_instance_id = chat_session_owner_instance_id(sender_session)
    if not sender_instance_id:
        return scope_workspace_id
    if instance_store is None:
        instance_store = PersonaInstanceStore()
    try:
        sender_instance = instance_store.get(sender_instance_id)
    except Exception:
        sender_instance = None
    if sender_instance is None:
        return scope_workspace_id
    return effective_workspace_id(sender_instance, active_workspace_id=active_workspace_id)


def resolve_default_chat_session_id_for_instance(
    store: "PersonaInstanceStore",
    *,
    persona_id: str,
    persona_instance_id: str | None = None,
) -> str | None:
    """Return the target's EXISTING default chat session id WITHOUT minting.

    Read the canonical instance pointer and return its bound session ONLY when it
    is a chat-shaped ``persona_chat_*`` session. Returns ``None`` when the target
    has never chatted (or its pointer is a task/worker session) — the honest
    "no thread yet" answer the read verbs (``agent_chat_threads`` /
    ``agent_chat_open``) surface instead of fabricating a session. Never writes.
    """
    instance_id = canonical_chat_instance_id(persona_id, persona_instance_id)
    try:
        existing = store.get(instance_id)
    except Exception:
        existing = None
    if existing is not None:
        existing_session = safe_assignment_text(
            getattr(existing, "default_chat_session_id", None), limit=200
        )
        # Reuse only a chat-shaped session: a task/worker session on the pointer
        # (task_bound mode) is not the persona's chat lane and must never absorb
        # a chat relay's transcript.
        #
        # AND only when it is THIS instance's own session. A pointer poisoned with
        # a SIBLING's session (``persona_chat_<other-instance>_<hex>``) must not be
        # adopted as this instance's default — that adoption is the sibling steal
        # that folded ``personainst_qa`` onto ``personainst_qa_agent_2``'s chat
        # lane (2026-07-18). A foreign pointer falls through to a fresh own mint,
        # self-healing the corrupted pointer on the next send.
        if (
            existing_session
            and existing_session.startswith(_PERSONA_CHAT_SESSION_PREFIX)
            and not chat_session_is_foreign_to_instance(existing_session, instance_id)
        ):
            return existing_session
    return None


def persona_id_from_instance_id(persona_instance_id: str) -> str:
    """Which persona does this instance id belong to? Row first, shape second."""

    token = safe_assignment_token(persona_instance_id)
    try:
        return PersonaInstanceStore().get(token).persona_id
    except Exception:
        pass
    if token.startswith("personainst_"):
        raw = token.removeprefix("personainst_")
        if raw.startswith("profile_"):
            profile = safe_assignment_token(raw.removeprefix("profile_"))
            if profile:
                return f"profile:{profile}"
        return normalize_persona_id(raw)
    try:
        return normalize_persona_id(token)
    except ValueError as exc:
        raise ValueError(f"unsupported persona instance {persona_instance_id!r}") from exc


def normalize_persona_or_template_id(persona_id: str) -> str:
    raw = str(persona_id or "").strip()
    if raw.lower().startswith("profile:"):
        profile = safe_assignment_token(raw.split(":", 1)[1])
        if not profile:
            raise ValueError(f"unsupported persona {persona_id!r}")
        return f"profile:{profile}"
    if safe_assignment_token(raw).startswith("personainst_"):
        # Mission Control payloads, legacy SessionDB rows, and agent tool calls
        # routinely leak persona INSTANCE ids into persona-id slots. Resolve
        # them here — the one persona-id boundary — instead of rejecting, so
        # every chat entry point accepts either form.
        return persona_id_from_instance_id(raw)
    return normalize_persona_id(raw)


def _persona_comparison_key(value: Any) -> str:
    """The ONE spelling a persona is compared under. Never called for display.

    Two folds, in a fixed order, because either one alone is a half-answer:
    ``normalize_persona_or_template_id`` resolves the FORM (an instance id in a
    persona slot, a ``profile:<name>`` channel, a bare persona id) but preserves
    the colon; ``safe_assignment_token`` flattens the punctuation but cannot
    resolve an instance id. Folding through both, in that order, is the only
    order that answers both questions.

    An id this module cannot normalize is tokenized as it arrived rather than
    dropped: two callers who both spell an unknown persona the same way still
    mean the same persona, and answering ``False`` there would silently widen a
    guard's refusal set.
    """

    try:
        canonical = normalize_persona_or_template_id(value)
    except Exception:
        canonical = value
    return safe_assignment_token(canonical)


def personas_equal(left: Any, right: Any) -> bool:
    """Do two persona spellings name the SAME persona?

    **Doctrine: one persona, one spelling authority — a guard must never compare
    the outputs of two different normalizers.**

    This function exists because a guard did exactly that, and the cost was a
    live outage. ``_cmd_mission_chat_message``'s ``foreign_chat_session`` fence
    compared ``normalize_persona_or_template_id(caller_persona)`` — which
    PRESERVES the colon, ``"profile:alice"`` — against
    ``safe_assignment_token(owner_instance.persona_id)`` — which REPLACES it,
    ``"profile_alice"``. One persona, two normalizers, one predicate: the two
    sides could never be equal, so every agent-to-agent reply delivery for a
    ``profile:`` persona was rejected as foreign and burned all eight delivery
    attempts against an identical, deterministic refusal
    (2026-08-24, dispatch-2540634d5cf3).

    Both sides fold through :func:`_persona_comparison_key` here, so there is
    exactly one authority and no call site can pick a different half of it.

    Empty on the LEFT is ``False``: "no persona was named" is never proof that
    two personas match, and a guard that read absence as agreement would accept
    precisely the requests it exists to refuse.
    """

    left_key = _persona_comparison_key(left)
    if not left_key:
        return False
    return left_key == _persona_comparison_key(right)
