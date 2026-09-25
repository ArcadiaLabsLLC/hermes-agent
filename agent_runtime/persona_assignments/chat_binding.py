"""The chat binding lane: open (bind) an instance's operator chat, refuse an
unbindable one, clear a binding, roll back a chat-root bind, and mint an operator
chat instance.

Functions over a ``PersonaInstanceStore`` (composition — the class binds each
one as a method).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hermes_time import now

from agent_runtime import paths
from agent_runtime.agent_create_phases import timed_create_subphase
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments.errors import RetiredPersonaInstanceError
from agent_runtime.persona_assignments.identity import (
    _display_name_for_template,
    _durable_chat_root,
    _normalize_instance_source_persona,
    _profile_id_for_persona_or_template,
    canonical_persona_instance_id,
    chat_session_is_foreign_to_instance,
    chat_session_owner_instance_id,
    persona_chat_session_id_for,
    persona_instance_id_for,
)
from agent_runtime.persona_assignments.vocabulary import _CHAT_MODES
from agent_runtime.serde import safe_assignment_text, safe_assignment_token
from agent_runtime.state_patches import (
    emit_persona_instance_create,
    emit_persona_instance_patch,
)
from agent_runtime.states import WorkerSessionState

if TYPE_CHECKING:
    from agent_runtime.persona_assignments.store import PersonaInstanceStore

__layer__ = "stores"

__all__ = [
    "assert_bindable",
    "clear_chat_session_binding",
    "create_operator_chat",
    "open_chat",
    "rollback_chat_root_bind",
]


def clear_chat_session_binding(
    store: PersonaInstanceStore,
    instance: PersonaInstance,
    *,
    session_id: str,
    reason: str,
) -> dict[str, Any] | None:
    """THE write path that unbinds one instance from a chat session.

    Nulls only the pointers that actually reference ``session_id``, demotes a
    conversational mode back to ``configured`` once the instance is left with
    no chat, persists once, and emits ``persona_instance.chat_binding_cleared``
    (store mutations always emit an event). Returns the repair record, or
    ``None`` when the instance never pointed at that session.

    Every STALE-binding clear — the operator ``persona chat delete`` verb and
    the ``repair_missing_chat_session_bindings`` reconcile sweep — goes
    through here, so a binding whose session is gone can never be reaped
    silently by one path and loudly by another.

    Why that claim is narrower than it used to be
    ---------------------------------------------
    It used to say "every unbind", and since ``b912cce88a`` that was false:
    :meth:`rollback_chat_root_bind` also nulls chat pointers, and it emits no
    ``chat_binding_cleared``. The sentence was corrected rather than made true
    by routing the retraction through here, because the retraction cannot
    become a call to this method without losing three properties it needs:

    * **It restores, it does not clear.** A retraction puts the row's PREVIOUS
      pointer back (a later mint failing must not orphan the conversation the
      instance already had). This method only ever nulls, and only the fields
      that match one ``session_id``.
    * **It must not raise.** It runs inside the failure handler of a lane that
      already holds a typed error; this method lets ``update`` propagate, and a
      rollback that masks its caller's cause is worse than the litter it sweeps.
    * **It must move the read model, and it is the ONLY thing that can.**
      The retraction emits ``emit_persona_instance_patch`` and appends
      nothing else — ``update`` is eventless — so with the patch removed the
      row write is invisible to the stream entirely, while the ``chat_opened``
      the failed bind already appended IS covered
      (:data:`patch_coverage.LIVE_COVERED_DOMAIN_EVENT_TYPES`) and can promote
      its batch to a patch frame. A connected client would fold the BIND and
      never hear the unbind. This method's event is uncovered and demotes the
      whole batch instead (see below), so routing the retraction through here
      would trade a false docstring for a genuinely stale client.

    Why this method emits NO ``state.patched``, measured rather than assumed
    ---------------------------------------------------------------------
    Not "because it emits a domain event" — the retraction's argument above
    is not the mirror image of that, and the sibling emits one too. The
    reason is what reaches the WIRE, and it was captured from a run:

    * ``persona_instance.chat_binding_cleared`` is deliberately absent from
      :data:`patch_coverage.COVERED_DOMAIN_EVENT_TYPES`. One uncovered event
      makes the whole coalesced batch uncoverable
      (:func:`patch_coverage.batch_is_patch_coverable`), so every frame
      carrying a clear ships with a full ``core`` attached and the client
      re-hydrates IN THAT SAME FRAME. There is no staleness window to close,
      and a ``state.patched`` emitted here would be a producer whose rows are
      discarded before the ``patches`` list is ever assembled — including
      when ``read_model.delta_patches`` is off, where the lane is a full core
      by design. This path is flag-independent; the retraction is not.
    * The demote is LOAD-BEARING, not an oversight waiting to be optimised.
      A clear also empties the instance's ``persona_chat_history`` row (the
      projection keys chat rows by ``default_chat_session_id``; drop the
      pointer and the row leaves the section outright), and there is no
      ``persona_chat_history`` patch entity for that to ride. Covering this
      event to make a patch reachable would therefore silently drop the
      chat-row departure from every connected client — the exact failure the
      ``persona_instance.chat_opened`` note in ``patch_coverage`` says the
      producer and the coverage entry must land together to avoid.

    Both halves are pinned as behaviour in ``test_persona_assignments.py``
    (the clear's batch demotes; covering it would drop a chat-history row),
    so this is a checkable claim rather than an assurance.

    The two paths are therefore both legitimate and both accounted for, and
    the count is fenced: ``test_persona_assignments.py`` walks this module's
    AST and fails if a THIRD function ever writes ``default_chat_session_id``
    or ``session_id`` on an instance.
    """

    target = safe_assignment_text(session_id, limit=200)
    if not target:
        return None
    cleared: list[str] = []
    if safe_assignment_text(instance.default_chat_session_id, limit=200) == target:
        instance.default_chat_session_id = None
        cleared.append("default_chat_session_id")
    if safe_assignment_text(instance.session_id, limit=200) == target:
        instance.session_id = None
        cleared.append("session_id")
    if not cleared:
        return None
    mode_before = instance.mode
    if (
        not instance.default_chat_session_id
        and not instance.session_id
        and (instance.mode or "").lower() in _CHAT_MODES
    ):
        instance.mode = "configured"
    updated = store.update(instance)
    payload = {
        "persona_id": updated.persona_id,
        "session_id": target,
        "cleared_fields": cleared,
        "mode_before": mode_before,
        "mode_after": updated.mode,
        "reason": reason,
    }
    store._event("persona_instance.chat_binding_cleared", updated, payload)
    return {"persona_instance_id": updated.id, **payload}


def assert_bindable(
    store: PersonaInstanceStore,
    *,
    persona_id: str,
    session_id: str | None = None,
    persona_instance_id: str | None = None,
) -> str:
    """Everything :meth:`open_chat` refuses, asserted WITHOUT writing anything.

    Returns the canonical instance id the bind would target, so a caller that
    needs to act before the bind derives that id ONCE, here, rather than
    re-deriving it and drifting.

    This exists because ``open_chat`` answers "may this bind happen?" only by
    RAISING at the end of whatever the caller already did. For
    :meth:`PersonaChatMintReceiptStore.mint` that end came after a session row
    had been created, meta written and a title set — so a dispatch to a target
    that could never be served left a permanent titled thread in Mission
    Control, and the refusal arrived one durable write too late. A refusal
    decidable without writing must be decidable WITHOUT writing, and it must be
    the SAME refusal: one derivation, one spelling of the target id, one
    retirement rule (:meth:`retired_instance_archive_path`).

    ``session_id`` is optional so a caller can ask "is this instance bindable
    at all?" before it has minted a root; when present it is checked for the
    sibling-steal the bind refuses. ``open_chat`` calls this first and is the
    write chokepoint, so this costs one extra row read on the bind path and
    buys the pre-flight callers an answer they can trust.
    """

    normalized_persona = _normalize_instance_source_persona(persona_id)
    if not normalized_persona:
        raise ValueError("persona_id is required")
    normalized_instance = (
        canonical_persona_instance_id(persona_instance_id, persona_id=normalized_persona)
        if persona_instance_id
        else None
    )
    instance_id = normalized_instance or persona_instance_id_for(normalized_persona)
    # A chat session encodes the instance it was minted for; binding one
    # instance's session onto ANOTHER instance's pointer is the sibling steal
    # that overwrote ``personainst_qa``'s default-chat pointer with a
    # placement sibling's session (live 2026-07-18: the console's open-chat of
    # a sibling bound its session onto the canonical primary, then a
    # bare-persona relay adopted the poisoned pointer — both instances folded
    # onto ONE operator channel). Refuse loudly at the write chokepoint every
    # send/open flows through — the existing ``_session_owned_by_other_instance``
    # guard only covered ``add_instance``. Legacy/opaque ``persona_chat_*``
    # sessions (no encoded owner) and the instance's own sessions bind freely.
    normalized_session = safe_assignment_text(session_id, limit=200)
    if normalized_session and chat_session_is_foreign_to_instance(
        normalized_session, instance_id
    ):
        owner = chat_session_owner_instance_id(normalized_session)
        raise ValueError(
            f"chat session {normalized_session!r} belongs to instance {owner!r}; "
            f"it cannot be bound onto {instance_id!r} — open that instance's own "
            "chat lane instead of adopting a sibling's session"
        )
    # ONE retirement rule, composed in one place (absence of a live row PLUS a
    # ``*_retire`` tombstone) and asked here by every caller that needs it.
    retired_archive = store.retired_instance_archive_path(instance_id)
    if retired_archive is not None:
        raise RetiredPersonaInstanceError(instance_id, archive_path=retired_archive)
    return instance_id


def open_chat(
    store: PersonaInstanceStore,
    *,
    persona_id: str,
    session_id: str,
    persona_instance_id: str | None = None,
    display_name: str | None = None,
    default_display_name: str | None = None,
    profile_id: str | None = None,
    kill_active: bool = False,
    workspace_id: str | None = None,
    realm_id: str | None = None,
) -> PersonaInstance:
    """Bind a persona instance to a durable chat session without running a turn.

    Persona instances are intentionally chat-shaped: selecting an old chat can
    re-open the same live persona instance history by rebinding the instance
    to the stored session id, while the normal send/resume path owns the actual
    LLM execution. A placement retired through :meth:`retire` is the explicit
    exception: its archived row is an end-of-life tombstone, so the preserved
    chat stays history-only and cannot recreate a live roster row. This helper
    is a state transition only; it never fabricates a task, worker, run, or
    transcript.
    """
    normalized_persona = _normalize_instance_source_persona(persona_id)
    normalized_session = safe_assignment_text(session_id, limit=200)
    if not normalized_persona:
        raise ValueError("persona_id is required")
    if not normalized_session:
        raise ValueError("session_id is required")

    # The bind's refusals — sibling steal and retirement — live in ONE
    # read-only seam so a pre-flight caller and the bind itself cannot
    # disagree about who this is or whether it may be bound.
    instance_id = store.assert_bindable(
        persona_id=persona_id,
        session_id=normalized_session,
        persona_instance_id=persona_instance_id,
    )
    from ..auxiliary_chat import is_auxiliary_chat

    if is_auxiliary_chat(instance_id, normalized_session):
        # assert_bindable above still enforces retirement and ownership.
        # An auxiliary open is never allowed to create/repoint an instance.
        return store.get(instance_id)
    safe_display_name = safe_assignment_text(display_name, limit=120) if display_name is not None else None
    safe_default_display_name = (
        safe_assignment_text(default_display_name, limit=120) if default_display_name is not None else None
    )
    safe_profile_id = safe_assignment_token(profile_id) if profile_id is not None else None
    instance, created = _load_or_mint_chat_instance(
        store,
        instance_id,
        normalized_persona,
        display_name=safe_display_name or safe_default_display_name,
        profile_id=safe_profile_id,
    )
    before = None if created else _tracked_fields(store, instance)
    _apply_open_fields(
        instance,
        normalized_persona=normalized_persona,
        display_name=safe_display_name,
        default_display_name=safe_default_display_name,
        profile_id=safe_profile_id,
        workspace_id=workspace_id,
        realm_id=realm_id,
    )
    # THE bind: both chat pointers move here, in ``open_chat`` itself, and
    # nowhere else on the open path.
    instance.mode = "chat"
    instance.default_chat_session_id = normalized_session
    # Read-compatible mirror for v1 consumers. Worker writers never touch
    # this field; default_chat_session_id is the sole new authority.
    instance.session_id = normalized_session
    previous_chat_head = _stamp_chat_head(instance)
    after = _tracked_fields(store, instance)
    if not created and before == after:
        # Idempotent re-open is an observation, not a mutation. Rewriting the
        # row would advance directory fingerprints and emitting
        # persona_instance.chat_opened would force a full-core stream delta.
        # One first-turn path legitimately reaches this chokepoint multiple
        # times; no-op calls must stay invisible to the event/read model.
        return instance
    return _commit_chat_opened(
        store,
        instance,
        created=created,
        moved_from=before,
        moved_to=after,
        session_id=normalized_session,
        previous_chat_head=previous_chat_head,
    )


def _tracked_fields(store: PersonaInstanceStore, instance: PersonaInstance) -> tuple[Any, ...]:
    return tuple(getattr(instance, field) for field in store._OPEN_CHAT_TRACKED_STORE_FIELDS)


def _load_or_mint_chat_instance(
    store: PersonaInstanceStore,
    instance_id: str,
    normalized_persona: str,
    *,
    display_name: str | None,
    profile_id: str | None,
) -> tuple[PersonaInstance, bool]:
    """The row to bind, and whether this open mints it."""
    try:
        return store.get(instance_id), False
    except Exception:
        # Worker/run ownership is orthogonal to operator chat ownership.
        # Opening another chat root must not cancel or rebind live work.
        pass
    ts = now()
    role = "profile" if normalized_persona.startswith("profile:") else normalized_persona
    instance = PersonaInstance(
        id=instance_id,
        persona_id=normalized_persona,
        role=role,
        display_name=display_name or _display_name_for_template(normalized_persona.split(":", 1)[1] if normalized_persona.startswith("profile:") else normalized_persona),
        profile_id=profile_id or (normalized_persona.split(":", 1)[1] if normalized_persona.startswith("profile:") else None),
        runtime_root=str(paths.store_root()),
        state=WorkerSessionState.IDLE,
        updated_at=ts,
    )
    return instance, True


def _apply_open_fields(
    instance: PersonaInstance,
    *,
    normalized_persona: str,
    display_name: str | None,
    default_display_name: str | None,
    profile_id: str | None,
    workspace_id: str | None,
    realm_id: str | None,
) -> None:
    """Name, profile and scope pointers of one bind (the chat pointers are
    ``open_chat``'s own)."""
    # An explicit ``display_name`` is AUTHORITATIVE — an operator naming this
    # chat (create_operator_chat) or a deliberate placement (add_instance,
    # "QA Agent (2)"); it always applies. A ``default_display_name`` is the
    # persona DEFAULT the SEND PATH stamps and must NEVER rename an existing
    # instance: applying it unconditionally clobbered a placement name —
    # ``personainst_qa_agent_2`` read "QA Agent" instead of "QA Agent (2)"
    # (the "(2)" is LOAD-BEARING: the launcher conversational fold keys on
    # persona+displayName, so the clobber folds a sibling onto the primary's
    # channel). Stamp the default only when the instance has NO name yet.
    # The one rename path stays ``persona.instance.update_profile``.
    if display_name:
        instance.display_name = display_name
    elif default_display_name and not safe_assignment_text(
        getattr(instance, "display_name", None), limit=120
    ):
        instance.display_name = default_display_name
    if profile_id:
        instance.profile_id = profile_id
    elif normalized_persona.startswith("profile:") and not instance.profile_id:
        instance.profile_id = normalized_persona.split(":", 1)[1]
    # Scope-provenance pointers: a provided workspace/realm is the caller's
    # authoritative placement-scope claim (the launcher stamps its active
    # scope when minting a placement) and applies on create AND re-open; an
    # omitted one never clears an existing pointer (plain chat re-opens
    # don't know scope and must not erase it).
    safe_workspace_id = safe_assignment_token(workspace_id) if workspace_id is not None else None
    safe_realm_id = safe_assignment_token(realm_id) if realm_id is not None else None
    if safe_workspace_id:
        instance.workspace_id = safe_workspace_id
    if safe_realm_id:
        instance.realm_id = safe_realm_id


def _stamp_chat_head(instance: PersonaInstance) -> str | None:
    """THE writer of the INSTANCE_RECORDED rung; returns the head it replaces.

    Stamp WHERE the bound conversation's transcript lives — the
    INSTANCE_RECORDED rung of ``chat_session_scope``. The send path
    re-enters this chokepoint every turn, so the stamp is re-affirmed
    per turn for free. Only an AUTHORITATIVE scope may stamp: recording
    a degraded ambient guess would launder the very guess the rung
    exists to retire, so an ambient bind leaves the field as it was
    (``None`` = explicitly UNRECORDED for readers). A re-stamp to a
    DIFFERENT authoritative head is deliberate and AUDITED, not silent:
    it changes the before/after tuple, so the row is rewritten and the
    ``chat_opened`` event carries both the new and previous head.
    """
    previous_chat_head = instance.chat_head_home
    from ..chat_session_scope import resolve_process_chat_scope

    # PROCESS ladder, deliberately — this is the site that WRITES the
    # INSTANCE_RECORDED rung, and ``normalized_session`` is in hand
    # right here, so omitting it would otherwise read as an oversight.
    # A writer that consulted its own rung would re-affirm a stale head
    # forever: the record would always agree with itself and the
    # pointer beneath it could never correct it.
    scope = resolve_process_chat_scope()
    if scope.authoritative:
        instance.chat_head_home = str(scope.head_home)
    return previous_chat_head


def _commit_chat_opened(
    store: PersonaInstanceStore,
    instance: PersonaInstance,
    *,
    created: bool,
    moved_from: tuple[Any, ...] | None,
    moved_to: tuple[Any, ...],
    session_id: str,
    previous_chat_head: str | None,
) -> PersonaInstance:
    """Write the bound row, emit its ``state.patched`` pair, append ``chat_opened``."""
    event_payload: dict[str, Any] = {"session_id": session_id}
    if instance.chat_head_home:
        event_payload["chat_head_home"] = instance.chat_head_home
    if previous_chat_head and previous_chat_head != instance.chat_head_home:
        event_payload["previous_chat_head_home"] = previous_chat_head
    with timed_create_subphase("instance_write_ms"):
        updated = store.update(instance)
    # S7-A producer: the PAIR ``persona_instance.chat_opened`` never had.
    #
    # Covering that event without this would be a silent data drop, not a
    # missed optimisation: ``open_chat`` writes real wire-visible state —
    # ``mode``, ``workspace_id``, ``realm_id``, ``profile_id``,
    # ``display_name`` and the ``default_chat_session_id`` trio, all present
    # in ``persona_instance_summary`` — and emitted no ``state.patched`` at
    # all, so a promoted batch would have advanced every connected client's
    # watermark past a row it never received.
    #
    # Two cases, split at ``created``:
    #
    # * RE-OPEN (``created=False``): the row exists on every client, so the
    #   diffed field subset folds as a merge. ``updated_at`` always rides,
    #   which is what keeps the pair from ever being EMPTY — a bind that
    #   moved only ``chat_head_home`` (no wire field) would otherwise emit
    #   nothing and leave the covered event riding alone.
    # * CREATE (``created=True``): a COMPLETE-row ``upsert`` stamped
    #   ``created: true``, gated behind the ``persona_instance_create``
    #   capability token so an un-updated launcher keeps receiving today's
    #   wire byte-for-byte (see ``emit_persona_instance_create``).
    #
    #   This arm emitted an ``op: refresh`` until D3 landed (plan §10.3,
    #   2026-08-16), and that one row was the entire cost of the operator's
    #   "add an agent" gesture: one unfoldable row demotes the whole batch,
    #   so it took the perfectly foldable ``office_actor created:true``
    #   upsert beside it down too and paid a full ``build_snapshot()`` —
    #   6.3–6.6 s of a measured 6.94 s gesture. The refresh's stated
    #   justification was that "a full persona-instance row cannot be assumed
    #   to fit the 4 KB cap", which was an assumption, not a measurement, and
    #   it outlived the R2 residue slimming that made it false. Measured on
    #   the live roster: worst assembled payload 3,133 bytes of 4,096. The
    #   emitter re-checks that per row and still degrades to ``refresh`` for
    #   any row that does not fit LOSSLESSLY, so the pre-D3 behaviour remains
    #   the floor rather than the norm.
    if created:
        with timed_create_subphase("create_patch_ms"):
            emit_persona_instance_create(store.event_log, updated)
    else:
        moved = [
            field
            for field, was, is_now in zip(
                store._OPEN_CHAT_TRACKED_STORE_FIELDS, moved_from or (), moved_to
            )
            if was != is_now
        ]
        emit_persona_instance_patch(
            store.event_log, updated, [*moved, "updated_at"]
        )
    with timed_create_subphase("event_append_ms"):
        store._event("persona_instance.chat_opened", updated, event_payload)
    return updated


def rollback_chat_root_bind(
    store: PersonaInstanceStore,
    *,
    persona_instance_id: str,
    root_session_id: str,
    previous: PersonaInstance | None,
) -> bool:
    """Undo an :meth:`open_chat` bind whose transcript row never landed.

    The EARLY-BIND ordering in
    :meth:`PersonaChatMintReceiptStore.mint` is deliberate — the bind is the
    step that proves the target still live, so it must precede the first
    SESSION-visible write (see the comment there; a retire landing mid-lane
    would otherwise leave a titled thread for a dead placement). The cost of
    that ordering is a window: if the ``create_session`` immediately after
    the bind FAILS, the pointer is already on the instance and names a root
    with no transcript row — the phantom
    :mod:`agent_runtime.persona_chat_durability` exists to make impossible,
    permanently undeliverable because
    :func:`resolve_default_chat_session_id_for_instance` re-offers a
    chat-shaped own-instance pointer forever without asking whether it
    resolves.

    This closes that window from the other side: the ordering stays, and the
    bind is RETRACTED when the write it was guarding could not be made.

    *previous* is the row as it stood BEFORE the bind, or ``None`` when the
    bind created it. Restoring ``None`` clears both pointer fields, which is
    the self-healing state — the resolver answers "no thread yet" and the
    next mint makes a fresh, durable root. The legacy ``session_id`` mirror
    is moved WITH the authority: ``PersonaInstance.__post_init__``
    re-derives ``default_chat_session_id`` from a ``persona_chat_*``
    ``session_id``, so clearing only the authority would resurrect the
    phantom on the next read. ``mode`` moves with them for the same reason —
    ``open_chat`` stamps ``chat`` as part of the bind, and a row left in that
    mode with no chat pointer is the very half-state
    :meth:`clear_chat_session_binding` demotes.

    Deliberately NOT routed through :meth:`clear_chat_session_binding`; see
    the "why the two paths stay separate" note in that method's docstring.

    Retracts on IDENTITY, never on mere presence: if the live pointer no
    longer names *root_session_id*, some other lane bound this instance
    after ours did, and its pointer is not ours to revert. Returns whether a
    retraction was written.
    """

    instance_id = safe_assignment_token(persona_instance_id)
    root = safe_assignment_text(root_session_id, limit=200)
    if not instance_id or not root:
        return False
    try:
        live = store.get(instance_id)
    except Exception:
        # No row to retract (or the store is unreadable). Either way this
        # must not raise: it runs inside the failure handler of a lane that
        # already has a typed error to report, and a rollback that masks the
        # original cause is worse than the litter it cleans.
        return False
    if safe_assignment_text(
        getattr(live, "default_chat_session_id", None), limit=200
    ) != root:
        return False
    restored_default = getattr(previous, "default_chat_session_id", None) if previous else None
    restored_legacy = getattr(previous, "session_id", None) if previous else None
    live.default_chat_session_id = restored_default
    live.session_id = restored_legacy
    # ``mode`` is restored WITH the pointers, because ``open_chat`` sets it
    # (``instance.mode = "chat"``) in the same breath as the bind this is
    # retracting. Reverting the pointers alone left the row in precisely the
    # state :meth:`clear_chat_session_binding` exists to demote away from —
    # ``mode == "chat"`` with no chat to be in — and that is not a cosmetic
    # inconsistency: ``persona_instance_summary`` ships ``mode`` on the wire,
    # the launcher decodes ``chat`` to ``MissionAgentInstanceMode.chatHistory``
    # (``mission_agent_instance.dart``), and its persona-best election ranks
    # ``chatHistory`` ABOVE ``configuredIdle``
    # (``mission_instance_resolution.dart``). A retracted fresh mint would
    # out-rank a genuinely idle sibling on the strength of a conversation
    # that was never written.
    #
    # ``previous.mode`` rather than a flat demotion, because this method
    # restores — it does not clear. A row that already had a working thread
    # keeps ``chat`` alongside the pointer being put back; a row the bind
    # CREATED has no previous mode, so it takes the store default
    # (``PersonaInstance.mode = "configured"``), which is the same value
    # ``clear_chat_session_binding`` demotes to.
    #
    # It rides the SAME staleness contract the pointers already ride, and no
    # stronger one: the identity guard above proves nothing re-bound the
    # POINTER since ``previous`` was read, not that nothing touched ``mode``.
    # A concurrent mode-only write inside that window would be reverted —
    # which is exactly what already happens to a concurrent pointer write
    # that kept our root, so this is the method's existing posture applied to
    # the field the bind set, not a new risk introduced beside it.
    live.mode = getattr(previous, "mode", None) or "configured"
    try:
        updated = store.update(live)
    except Exception:
        logging.getLogger(__name__).warning(
            "could not retract the chat-root bind for %s; "
            "its default chat pointer may name an unwritten transcript",
            instance_id,
            exc_info=True,
        )
        return False
    # The bind emitted a create/patch onto the read model; the retraction
    # must emit its counterpart or every connected client keeps showing the
    # phantom pointer the store no longer holds.
    emit_persona_instance_patch(
        store.event_log,
        updated,
        ["mode", "session_id", "default_chat_session_id", "updated_at"],
    )
    return True


def create_operator_chat(
    store: PersonaInstanceStore,
    *,
    persona_id: str,
    display_name: str,
    session_id: str | None = None,
    kill_active: bool = False,
) -> PersonaInstance:
    normalized_persona = _normalize_instance_source_persona(persona_id)
    instance_id = persona_instance_id_for(normalized_persona)
    root = session_id or persona_chat_session_id_for(instance_id)
    # Refusals FIRST, durable writes second — the ordering
    # ``PersonaChatMintReceiptStore.mint`` already learned. Persisting the
    # root before the bind is checked would leave a titled Mission Control
    # thread behind every retirement/sibling-steal refusal; ``open_chat``
    # re-asserts this, so the pre-flight only moves the answer earlier.
    store.assert_bindable(
        persona_id=normalized_persona,
        session_id=root,
        persona_instance_id=instance_id,
    )
    return store.open_chat(
        persona_id=normalized_persona,
        persona_instance_id=instance_id,
        session_id=_durable_chat_root(
            root,
            persona_id=normalized_persona,
            # An explicit ``display_name`` is authoritative in ``open_chat``,
            # so this is exactly the title the argv lane's post-hoc ensure
            # would have written — and that ensure never overwrites an
            # existing title, so the two lanes agree by construction.
            display_name=display_name,
        ),
        display_name=display_name,
        profile_id=_profile_id_for_persona_or_template(normalized_persona),
        kill_active=kill_active,
    )
