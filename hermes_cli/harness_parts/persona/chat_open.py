"""Open a persona chat: ``persona instance open-chat`` / ``open-new-chat`` and their payload emitters.

Separate because opening binds a session to an instance and prewarms its actor;
it never runs a turn.
"""

from __future__ import annotations

from dataclasses import asdict
from agent_runtime.chat_session_scope import is_canonical_session_persistence
from agent_runtime.cli_format import emit_json
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.coordinator_permissions import review_coordinator_budget
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    RetiredPersonaInstanceError,
    canonical_persona_instance_id,
    chat_session_owner_instance_id,
    normalize_persona_or_template_id as _normalize_cli_persona_or_template_id,
    persona_chat_session_id_for,
    persona_instance_id_for,
    personas_equal,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError,
    default_persona_session_db as _default_persona_session_db,
    ensure_persona_chat_session as _ensure_persona_chat_session,
)
from agent_runtime.persona_chat_mints import PersonaChatMintError, reserve_persona_chat_mint
from .chat_coordinator import (
    _coordinator_actor_id,
    _coordinator_confirm_payload,
    _coordinator_scope_from_args,
    _maybe_stamp_spawned_by,
)
from .chat_request import _retired_persona_instance_payload
from .chat_session import _persona_chat_session_owner
from .chat_target import _persona_by_id
from .lifecycle_commands import _placement_discriminability_refusal

__layer__ = "lanes"
__all__ = [
    "_cmd_persona_instance_open_chat",
    "_cmd_persona_instance_open_new_chat",
    "_emit_persona_open_chat_payload",
]


def _cmd_persona_instance_open_chat(args) -> int:
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import ChatErrorKind
    cfg = load_agent_runtime_config()
    persona_id = _normalize_cli_persona_or_template_id(args.persona_id)
    persona = _persona_by_id(cfg, persona_id)
    coordinator_id = _coordinator_actor_id(args)
    coordinator_scope = None
    if coordinator_id and bool(getattr(args, "add_instance", False)):
        coordinator_scope = _coordinator_scope_from_args(args, cfg, persona)
        auth = review_coordinator_budget(
            "persona.instance.open_chat",
            coordinator_scope,
            actor=coordinator_id,
            coordinator_id=coordinator_id,
        )
        if not auth.ok:
            data = _coordinator_confirm_payload("persona.instance.open_chat", coordinator_id, auth)
            _emit_persona_open_chat_payload(args, data, plain=data["status"])
            return 2
        coordinator_scope = auth.scope
    elif coordinator_id and bool(getattr(args, "kill_active", False)):
        coordinator_scope = _coordinator_scope_from_args(args, cfg, persona)
        try:
            target = PersonaInstanceStore().get(persona_instance_id_for(persona_id))
        except Exception:
            target = None
        auth = review_coordinator_budget(
            "persona.instance.close",
            coordinator_scope,
            target,
            actor=coordinator_id,
            coordinator_id=coordinator_id,
        )
        if not auth.ok:
            data = _coordinator_confirm_payload("persona.instance.close", coordinator_id, auth)
            _emit_persona_open_chat_payload(args, data, plain=data["status"])
            return 2
    if bool(getattr(args, "new_session", False)):
        return _cmd_persona_instance_open_new_chat(
            args,
            persona_id=persona_id,
            coordinator_scope=coordinator_scope,
        )
    previous_instance = None
    try:
        if bool(getattr(args, "add_instance", False)):
            placement_id = safe_assignment_token(getattr(args, "placement_id", None))
            if not placement_id:
                data = {"ok": False, "error": "placement_id is required when add_instance is true"}
                _emit_persona_open_chat_payload(args, data)
                return 2
            # UC-H4, scoped to --add-instance ONLY. The other branches of this
            # verb REBIND an instance that already exists (and the recorded
            # 2026-07-25 recovery replayed ten of them out of the event log);
            # they mint nothing, so a roster check there would refuse a repair
            # for a persona whose config row went away — the exact workflow the
            # refusal must not break. Minting is the thing being fenced.
            from agent_runtime.agent_create import require_known_persona

            refusal = require_known_persona(persona_id, persona)
            if refusal is not None:
                _emit_persona_open_chat_payload(args, refusal)
                return 2
            # AFTER the roster check, matching the order `persona instance
            # create` already had: "that agent does not exist" is the more
            # fundamental answer than "that id is the wrong shape", and an
            # operator who typed both mistakes should hear the one that is
            # about the agent. Both still refuse before any store write.
            placement_refusal = _placement_discriminability_refusal(placement_id)
            if placement_refusal is not None:
                _emit_persona_open_chat_payload(args, placement_refusal)
                return 2
            try:
                # Local import. Before lane H1 this file was exec'd into
                # harness.py's globals, and as a free name this raised NameError
                # on every --add-instance and the except below swallowed it,
                # silently disabling the named-placement preservation described in
                # the comment that follows (found by the 2026-07-31 audit).
                from agent_runtime.persona_assignments import (
                    persona_instance_id_for_placement,
                )

                previous_instance = PersonaInstanceStore().get(
                    persona_instance_id_for_placement(placement_id)
                )
            except Exception:
                previous_instance = None
            # A deliberately-placed additional instance ("QA Agent (2)") carries
            # its distinct name so the operator's placement cue survives into the
            # store, the launcher conversational fold (keyed on
            # persona+display_name), and the HUD roster. When the client omits it
            # the honest fallback is the persona's OWN configured display name
            # ("QA Agent"), never the title-cased persona id ("Qa") the store
            # template fallback would otherwise mint.
            #
            # That rule is now ONE copy, in ``agent_runtime.agent_create``, because
            # ``runtime.agent.create`` mints the same placements over the method
            # lane and calling the store directly would have dropped it silently.
            # This lane still passes the persona object it already resolved
            # through its own richer ``_persona_by_id``, so its behaviour is
            # unchanged; the shared function only supplies the fallback ladder.
            from agent_runtime.agent_create import (
                honest_default_display_name as _honest_default_display_name,
            )

            explicit_display_name = safe_assignment_text(getattr(args, "display_name", None), limit=120)
            honest_default_display_name = _honest_default_display_name(
                persona_id, persona
            )
            instance = PersonaInstanceStore().add_instance(
                persona_id=persona_id,
                placement_id=placement_id,
                session_id=args.session_id,
                display_name=explicit_display_name,
                default_display_name=honest_default_display_name,
                workspace_id=safe_assignment_token(getattr(args, "workspace_id", None)) or None,
                realm_id=safe_assignment_token(getattr(args, "realm_id", None)) or None,
            )
            instance = _maybe_stamp_spawned_by(instance, coordinator_id=coordinator_id)
        else:
            if not safe_assignment_text(getattr(args, "session_id", None), limit=200):
                data = {"ok": False, "error": "session_id is required unless add_instance is true"}
                _emit_persona_open_chat_payload(args, data)
                return 2
            # RETIREMENT, asked before the session-existence cutoff below.
            # Retiring a placement archives the row but deliberately leaves its
            # chat on disk, so an operator (or a stale launcher frame) re-opening
            # that thread is asking about something that HAS a typed end-of-life
            # answer — the tombstone and "history preserved". It used to get
            # `unknown_chat_session` instead, which names the wrong fact and
            # offers the wrong next step ("open a server-minted chat root").
            #
            # The owner comes from the session id itself (`persona_chat_<
            # instance>_<hex>` encodes it), so this answers even when the row is
            # archived and no SessionDB entry survives — precisely the case that
            # read as "unknown". Read-only, through the ONE bind seam, so a live
            # row always wins and a legitimately re-created placement is never
            # refused by its own history. A bare persona resolves to the
            # canonical channel, which cannot be retired.
            PersonaInstanceStore().assert_bindable(
                persona_id=persona_id,
                # No session_id: the sibling-steal refusal is a ValueError, and
                # the `foreign_chat_session` guard below already owns that answer
                # with the envelope the operator needs.
                persona_instance_id=(
                    safe_assignment_token(getattr(args, "persona_instance_id", None))
                    or chat_session_owner_instance_id(args.session_id)
                    or None
                ),
            )
            session_db = _default_persona_session_db()
            if (
                is_canonical_session_persistence(session_db)
                and session_db.get_session(args.session_id) is None
            ):
                data = {
                    "ok": False,
                    "error_kind": ChatErrorKind.UNKNOWN_CHAT_SESSION,
                    "error": f"unknown explicit persona chat root: {args.session_id}",
                }
                _emit_persona_open_chat_payload(args, data)
                return 2
            target_instance_id = safe_assignment_token(
                getattr(args, "persona_instance_id", None)
            ) or None
            if is_canonical_session_persistence(session_db):
                session_owner = _persona_chat_session_owner(session_db, args.session_id)
                try:
                    owner_instance = (
                        PersonaInstanceStore().get(session_owner)
                        if session_owner
                        else None
                    )
                except Exception:
                    owner_instance = None
                # Same two-normalizer defect as the mission-chat fence, one verb
                # over: ``safe_assignment_token(owner.persona_id)`` (token form)
                # against ``persona_id``, which is
                # ``_normalize_cli_persona_or_template_id`` output (colon form).
                # ``personas_equal`` folds both sides through one authority; the
                # pin leg is bounded exactly as it is there (ownership proof, not
                # persona proof).
                owner_persona = getattr(owner_instance, "persona_id", None)
                pin_proves_ownership = bool(target_instance_id) and (
                    target_instance_id == session_owner
                )
                persona_ok = personas_equal(owner_persona, persona_id) or (
                    pin_proves_ownership and not safe_assignment_token(owner_persona)
                )
                if (
                    owner_instance is None
                    or not persona_ok
                    or (target_instance_id and target_instance_id != session_owner)
                ):
                    data = {
                        "ok": False,
                        "error_kind": ChatErrorKind.FOREIGN_CHAT_SESSION,
                        "error": f"explicit chat root is not owned by the target instance: {args.session_id}",
                        "persona_id": persona_id,
                        "session_id": args.session_id,
                        "next_expected": "use the server-minted root returned for this exact persona instance",
                    }
                    _emit_persona_open_chat_payload(args, data)
                    return 2
                target_instance_id = session_owner
            try:
                previous_instance = PersonaInstanceStore().get(
                    target_instance_id or persona_instance_id_for(persona_id)
                )
            except Exception:
                previous_instance = None
            try:
                instance = PersonaInstanceStore().open_chat(
                    persona_id=persona_id,
                    persona_instance_id=target_instance_id,
                    session_id=args.session_id,
                    kill_active=bool(getattr(args, "kill_active", False)),
                )
            except ValueError as exc:
                data = {
                    "ok": False,
                    "error_kind": ChatErrorKind.FOREIGN_CHAT_SESSION,
                    "error": safe_assignment_text(str(exc), limit=320),
                    "persona_id": persona_id,
                    "session_id": args.session_id,
                    "next_expected": "open the instance that owns this chat session, or start a fresh thread",
                }
                _emit_persona_open_chat_payload(args, data)
                return 2
    except RetiredPersonaInstanceError as exc:
        data = _retired_persona_instance_payload(exc)
        _emit_persona_open_chat_payload(args, data)
        return 2
    except PersonaChatPersistenceError as exc:
        # ``add_instance``'s mint refuses rather than binding an unpersistable
        # root, so the persist failure can now arrive BEFORE the bind. Same
        # typed frame the post-bind arm below emits.
        data = {
            "ok": False,
            "error_kind": ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
            "persistence_operation": exc.operation,
            "error": str(exc),
            "persona_id": persona_id,
            "next_expected": "restore canonical persona chat transcript storage and retry",
        }
        _emit_persona_open_chat_payload(args, data)
        return 2
    try:
        _ensure_persona_chat_session(
            session_db=_default_persona_session_db(),
            session_id=instance.default_chat_session_id,
            persona_id=instance.persona_id,
            title=f"{instance.display_name} chat",
            required=True,
        )
    except PersonaChatPersistenceError as exc:
        data = {
            "ok": False,
            "error_kind": ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
            "persistence_operation": exc.operation,
            "error": str(exc),
            "persona_id": instance.persona_id,
            "persona_instance_id": instance.id,
            "session_id": instance.default_chat_session_id,
            "next_expected": "restore canonical persona chat transcript storage and retry",
        }
        _emit_persona_open_chat_payload(args, data)
        return 2
    # Placed AFTER the transcript row is durable (the ensure above) so the warm
    # can read the root's native tip and revision — the two values that decide
    # whether the first turn REUSES the actor or rebuilds it. See the helper.
    _prewarm_chat_actor_for_open(instance.default_chat_session_id)
    previous_session_id = (
        safe_assignment_text(
            getattr(previous_instance, "default_chat_session_id", None)
            or getattr(previous_instance, "session_id", None),
            limit=200,
        )
        if previous_instance is not None
        else None
    )
    instance_updated_at = _persona_instance_updated_at(instance)
    previous_updated_at = _persona_instance_updated_at(previous_instance)
    binding_changed = (
        previous_instance is None
        or previous_session_id != instance.default_chat_session_id
        or getattr(previous_instance, "mode", None) != instance.mode
        or previous_updated_at != instance_updated_at
    )
    data = {
        "ok": True,
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "mode": instance.mode,
        "default_chat_session_id": instance.default_chat_session_id,
        "session_id": instance.default_chat_session_id,
        "previous_session_id": previous_session_id,
        "binding_receipt": {
            "schema_version": 1,
            "persona_instance_id": instance.id,
            "session_id": instance.default_chat_session_id,
            "previous_session_id": previous_session_id,
            "changed": binding_changed,
            "instance_updated_at": instance_updated_at,
        },
        "chat_busy": False,
        "killed_previous": bool(getattr(args, "kill_active", False)),
        "add_instance": bool(getattr(args, "add_instance", False)),
        "placement_id": safe_assignment_token(getattr(args, "placement_id", None)) or None,
        "coordinator_permission_scope": asdict(coordinator_scope) if coordinator_scope is not None else None,
        "next_expected": "resume or send on this chat session to boot the persona instance history",
    }
    _emit_persona_open_chat_payload(
        args,
        data,
        plain=f"opened {instance.id} on chat {instance.default_chat_session_id}",
    )
    return 0


def _persona_instance_updated_at(instance) -> str | None:
    if instance is None:
        return None
    value = getattr(instance, "updated_at", None)
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return safe_assignment_text(value, limit=80) or None


def _cmd_persona_instance_open_new_chat(args, *, persona_id: str, coordinator_scope) -> int:
    """Mint one exact-instance chat root with durable retry semantics."""
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import ChatErrorKind
    if bool(getattr(args, "add_instance", False)):
        return _emit_persona_open_chat_error(
            args,
            error_kind=ChatErrorKind.INVALID_REQUEST,
            error="new_session and add_instance are mutually exclusive",
            persona_id=persona_id,
        )
    if safe_assignment_text(getattr(args, "session_id", None), limit=200):
        return _emit_persona_open_chat_error(
            args,
            error_kind=ChatErrorKind.INVALID_REQUEST,
            error="session_id must be omitted when new_session is true",
            persona_id=persona_id,
        )

    requested_instance_id = safe_assignment_token(
        getattr(args, "persona_instance_id", None)
    )
    target_instance_id = (
        canonical_persona_instance_id(requested_instance_id, persona_id=persona_id)
        if requested_instance_id
        else persona_instance_id_for(persona_id)
    )
    store = PersonaInstanceStore()
    try:
        current = store.get(target_instance_id)
    except Exception:
        return _emit_persona_open_chat_error(
            args,
            error_kind=ChatErrorKind.PERSONA_INSTANCE_NOT_FOUND,
            error=f"persona instance not found: {target_instance_id}",
            persona_id=persona_id,
            persona_instance_id=target_instance_id,
            next_expected="refresh the Harness roster and retry against a live persona instance",
        )
    # Fourth site of the shape: the STORED persona compared raw against
    # ``_normalize_cli_persona_or_template_id`` output. One authority, both sides
    # — a spelling difference is not an instance mismatch.
    if not personas_equal(current.persona_id, persona_id):
        return _emit_persona_open_chat_error(
            args,
            error_kind=ChatErrorKind.PERSONA_INSTANCE_MISMATCH,
            error=(
                f"persona instance {target_instance_id!r} belongs to "
                f"{current.persona_id!r}, not {persona_id!r}"
            ),
            persona_id=persona_id,
            persona_instance_id=target_instance_id,
        )

    try:
        with reserve_persona_chat_mint(
            idempotency_key=getattr(args, "idempotency_key", None),
            persona_id=persona_id,
            persona_instance_id=target_instance_id,
            session_id=persona_chat_session_id_for(target_instance_id),
        ) as mint:
            receipt = mint.receipt
            if receipt.bound:
                # A retry after a confirmed response loss must be observational:
                # return the original root without moving the instance pointer
                # back over a newer chat selected since this mint completed.
                instance = store.get(target_instance_id)
            else:
                # Make the transcript root durable before publishing it as the
                # instance's selected chat. If SessionDB is temporarily
                # unavailable the reserved receipt survives and retry reuses the
                # same root instead of creating a duplicate conversation.
                try:
                    _ensure_persona_chat_session(
                        session_db=_default_persona_session_db(),
                        session_id=receipt.session_id,
                        persona_id=persona_id,
                        title=f"{current.display_name} chat",
                        required=True,
                    )
                except PersonaChatPersistenceError as exc:
                    data = {
                        "ok": False,
                        "error_kind": ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
                        "persistence_operation": exc.operation,
                        "error": str(exc),
                        "persona_id": persona_id,
                        "persona_instance_id": target_instance_id,
                        "session_id": receipt.session_id,
                        "mission_chat_root_id": receipt.session_id,
                        "idempotent_replay": receipt.idempotent_replay,
                        "mint_receipt_state": receipt.state,
                        "next_expected": "restore canonical persona chat transcript storage and retry with the same idempotency key",
                    }
                    _emit_persona_open_chat_payload(args, data)
                    return 2
                try:
                    instance = store.open_chat(
                        persona_id=persona_id,
                        persona_instance_id=target_instance_id,
                        session_id=receipt.session_id,
                        kill_active=bool(getattr(args, "kill_active", False)),
                    )
                except RetiredPersonaInstanceError as exc:
                    data = _retired_persona_instance_payload(exc)
                    data.update(
                        {
                            "session_id": receipt.session_id,
                            "mission_chat_root_id": receipt.session_id,
                            "idempotent_replay": receipt.idempotent_replay,
                            "mint_receipt_state": receipt.state,
                        }
                    )
                    _emit_persona_open_chat_payload(args, data)
                    return 2
                receipt = mint.mark_bound()
    except PersonaChatMintError as exc:
        return _emit_persona_open_chat_error(
            args,
            error_kind=exc.code,
            error=str(exc),
            persona_id=persona_id,
            persona_instance_id=target_instance_id,
        )

    # The highest-value prewarm in the harness: a freshly minted root has no
    # turn that is not its first, so without this EVERY new chat pays the cold
    # construction on the operator's opening message. The mint is bound and the
    # transcript row is durable by this line.
    _prewarm_chat_actor_for_open(receipt.session_id)
    selected = instance.session_id == receipt.session_id
    data = {
        "ok": True,
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "mode": instance.mode,
        "session_id": receipt.session_id,
        "mission_chat_root_id": receipt.session_id,
        "chat_busy": False,
        "killed_previous": bool(getattr(args, "kill_active", False)),
        "add_instance": False,
        "new_session": True,
        "selected": selected,
        "superseded": not selected,
        "idempotent_replay": receipt.idempotent_replay,
        "mint_receipt_state": receipt.state,
        "coordinator_permission_scope": asdict(coordinator_scope)
        if coordinator_scope is not None
        else None,
        "next_expected": "resume or send on this server-minted chat root",
    }
    _emit_persona_open_chat_payload(
        args,
        data,
        plain=f"opened {instance.id} on new chat {receipt.session_id}",
    )
    return 0


def _prewarm_chat_actor_for_open(session_id) -> None:
    """Queue this chat root's resident actor for background construction.

    Stage 2 of ``planned/chat-turn-prep-cost``: the FIRST turn of a chat root
    pays ~3 s of agent construction on the operator's critical path, and a
    freshly minted chat has no turn that is not its first. Building the actor
    when the chat is OPENED moves that cost off the turn.

    Called from the two open-chat arms and NOWHERE else — in particular not from
    ``PersonaInstanceStore.open_chat``, which the send path re-enters on every
    turn: hooking the store method would fire a background construction against
    every live turn, which is the contention the prewarm's yield rule exists to
    avoid. These two arms are the operator's gesture; the launcher fires
    ``persona.instance.open_chat`` when a chat is opened or created and never
    when a message is sent.

    Inert without a resident registry — every CLI one-shot, and any serve with
    ``persona_chat.hot_sessions_enabled`` off — and best effort by contract: an
    open must never fail because a warm could not be queued.
    """

    try:
        from agent_runtime.persona_chat_actor_prewarm import request_chat_actor_prewarm

        request_chat_actor_prewarm(session_id)
    except Exception:
        pass


def _emit_persona_open_chat_payload(args, data: dict, *, plain: str | None = None) -> None:
    """Hand ONE open-chat payload to whoever owns this call's transport.

    The exact seam ``_emit_mission_chat_payload`` is for the send lane, one verb
    over, and it exists for the same reason and against the same alternative.
    ``runtime.persona.instance.open_chat`` (plan C1h, ruling R-C5) is an
    IN-PROCESS second door onto this handler, running on a serve's reader loop —
    so the only other way for it to read the row would be
    ``contextlib.redirect_stdout``, which rebinds ``sys.stdout``
    PROCESS-GLOBALLY and would briefly steal the serve's own frame protocol from
    every other thread on it. That argument is written out in full at
    :func:`_emit_mission_chat_payload`; nothing about it is weaker here.

    ``args.payload_sink`` is the seam, and it is absent on every argparse
    Namespace, so the CLI and the serve's argv bridge are untouched: with no
    sink this prints byte-for-byte what each call site printed before.

    ``plain`` is the non-JSON console line; ``None`` keeps the historical
    ``data["error"]``. Deliberately no ``stream`` arm — opening a chat is not a
    turn and has never had one.
    """

    sink = getattr(args, "payload_sink", None)
    if callable(sink):
        sink(data)
        return
    print(emit_json(data) if args.json else (data["error"] if plain is None else plain))


def _emit_persona_open_chat_error(
    args,
    *,
    error_kind: str,
    error: str,
    persona_id: str,
    persona_instance_id: str | None = None,
    next_expected: str = "correct the open-chat request and retry",
) -> int:
    data = {
        "ok": False,
        "error_kind": error_kind,
        "error": safe_assignment_text(error, limit=400),
        "persona_id": persona_id,
        "persona_instance_id": persona_instance_id,
        "next_expected": next_expected,
    }
    _emit_persona_open_chat_payload(args, data)
    return 2
