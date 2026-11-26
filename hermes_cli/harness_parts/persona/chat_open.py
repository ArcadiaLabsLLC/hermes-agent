"""Open a persona chat: ``persona instance open-chat`` / ``open-new-chat`` and their payload emitters.

Separate because opening binds a session to an instance and prewarms its actor;
it never runs a turn.
"""

from __future__ import annotations

from dataclasses import asdict
from contextlib import closing
from agent_runtime.conversation_owner import ConversationOwnerError, require_session_owner
from agent_runtime.chat_session_scope import is_canonical_session_persistence
from agent_runtime.chat_heads import resolve_conversation_chat_scope
# Patched by the open-chat tests' config seam; the open itself no longer reads the roster.
from agent_runtime.config import load_agent_runtime_config  # noqa: F401
from agent_runtime.persona_assignments import (
    AgentNotPlacedError,
    PersonaInstanceStore,
    RetiredPersonaInstanceError,
    canonical_persona_instance_id,
    chat_session_owner_instance_id,
    normalize_persona_or_template_id as _normalize_cli_persona_or_template_id,
    persona_instance_id_for,
    personas_equal,
    placed_instance_for,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError,
    default_persona_session_db as _default_persona_session_db,
    ensure_persona_chat_session as _ensure_persona_chat_session,
    persona_session_db_for,
)
from agent_runtime.persona_chat_continuity import mint_chat_root
from agent_runtime.persona_chat_mints import PersonaChatMintError
from .chat_request import _emit_persona_verb_payload, _retired_persona_instance_payload
from agent_runtime.persona_chat_session import _persona_chat_session_owner
from .lifecycle_commands import _instance_session_db

__layer__ = "lanes"
__all__ = [
    "_cmd_persona_instance_open_chat",
    "_cmd_persona_instance_open_new_chat",
    "_emit_persona_verb_payload",
]


def _conversation_session_db(args):
    """The writer for an explicit ``--session-id`` open: that conversation's own head.

    The scope is resolved from the session id and the caller's instance pin, so
    a per-profile conversation is written in its profile and never in base.
    """

    return persona_session_db_for(
        resolve_conversation_chat_scope(
            session_id=args.session_id,
            persona_instance_id=safe_assignment_token(
                getattr(args, "persona_instance_id", None)
            ) or None,
        ),
        process=_default_persona_session_db,
    )


def _cmd_persona_instance_open_chat(args) -> int:
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import ChatErrorKind
    persona_id = _normalize_cli_persona_or_template_id(args.persona_id)
    if bool(getattr(args, "add_instance", False)):
        # RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT (review w1118a.74): opening a
        # chat no longer places an agent. Nothing sent it any more (Eternia's argv lane is gone
        # and the method lane pins the key closed); a seat is ``runtime.agent.place``'s, or its
        # argv twin ``persona instance create --add-instance``. Refused before any write.
        # MUTATION: drop this refusal and test_open_chat_add_instance_is_refused_naming_the_place reddens.
        from agent_runtime.agent_create.outcome import placing_door_moved

        refusal = {**placing_door_moved("add_instance"),
                   "next_expected": "place the agent with `harness persona instance create --add-instance "
                                    "--workspace-id <id>` (runtime.agent.place), then open its chat"}
        _emit_persona_verb_payload(args, refusal, plain=refusal["error"])
        return 2
    coordinator_scope = None
    if bool(getattr(args, "new_session", False)):
        return _cmd_persona_instance_open_new_chat(
            args,
            persona_id=persona_id,
            coordinator_scope=coordinator_scope,
        )
    previous_instance = None
    move_to = moved_from = None
    try:
        if not safe_assignment_text(getattr(args, "session_id", None), limit=200):
            data = {"ok": False, "error": "session_id is required unless new_session is true"}
            _emit_persona_verb_payload(args, data)
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
        session_db = _conversation_session_db(args)
        if (
            is_canonical_session_persistence(session_db)
            and session_db.get_session(args.session_id) is None
        ):
            data = {
                "ok": False,
                "error_kind": ChatErrorKind.UNKNOWN_CHAT_SESSION,
                "error": f"unknown explicit persona chat root: {args.session_id}",
            }
            _emit_persona_verb_payload(args, data)
            return 2
        target_instance_id = safe_assignment_token(
            getattr(args, "persona_instance_id", None)
        ) or None
        if is_canonical_session_persistence(session_db):
            try:
                require_session_owner(session_db.get_session(args.session_id),
                                      getattr(args, "client_scope", None))
            except ConversationOwnerError as exc:
                return _emit_persona_open_chat_error(args, error_kind=exc.reason,
                    error="This conversation belongs to another account.", persona_id=persona_id)
            session_owner = _persona_chat_session_owner(session_db, args.session_id)
            try:
                owner_instance = (
                    PersonaInstanceStore().get(session_owner)
                    if session_owner
                    else None
                )
            except Exception:
                # A retired holder answers from its archive (review w1118a.56
                # D13): its old chat can still move onto a live instance of the
                # same agent; without ``move`` it is refused below as before.
                owner_instance = PersonaInstanceStore().retired_instance_row(session_owner)
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
            # A saved chat held by the agent's bare id (its old hidden copy, no row under it) opens on the
            # agent's placed instance: an idle one takes it as its live chat, else a new one is placed
            # (RT-FU-A-CHAT-OPENED-ON-AN-AGENTS-BARE-NAME-NO-LONGER-MAKES-A-HELD-ROW, owner RULED 2026-11-22).
            # MUTATION: skip this arm and test_a_saved_chat_on_an_agents_bare_name_replaces_the_idle_instances_chat reddens.
            bare_agent = (_unplaced_agent_named_by(session_owner, persona_id)
                          if owner_instance is None and target_instance_id in (None, session_owner) else None)
            if bare_agent is not None:
                placed = _place_for_bare_open(args, bare_agent)
                if isinstance(placed, int):
                    return placed
                move_to = placed
            else:
                move_to = _move_target(args, owner_instance, persona_ok,
                                       target_instance_id, session_owner)
            if move_to is None and (
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
                _emit_persona_verb_payload(args, data)
                return 2
            target_instance_id = move_to or session_owner
        if move_to is None:
            # The bind would land on the agent's bare id (no instance named, or its old hidden copy named
            # with no row under it): the door places first, by the one reuse-or-place rule, so the store's
            # ``agent_not_placed`` guard never answers an operator's open.
            # MUTATION: drop this placement and test_a_bare_open_with_no_idle_instance_places_one_and_announces_it reddens.
            bare_agent = _unplaced_agent_named_by(
                target_instance_id or persona_instance_id_for(persona_id), persona_id)
            if bare_agent is not None:
                placed = _place_for_bare_open(args, bare_agent)
                if isinstance(placed, int):
                    return placed
                target_instance_id = placed
        try:
            # The instance the chat opens on, else the agent's placed instance: never the hidden copy
            # ``personainst_<persona>`` nothing mints any more
            # (RT-FU-THE-LAST-READERS-THAT-GUESS-AN-AGENTS-HIDDEN-COPY-NAME-ASK-FOR-ITS-PLACED-INSTANCE).
            previous_instance = (
                PersonaInstanceStore().get(target_instance_id)
                if target_instance_id
                else placed_instance_for(persona_id)
            )
        except Exception:
            previous_instance = None
        try:
            bound = _bind_for_open(args, session_db, move_to, persona_id, target_instance_id)
            if isinstance(bound, int):
                return bound
            instance, moved_from = bound
        except ValueError as exc:
            data = {
                "ok": False,
                "error_kind": ChatErrorKind.FOREIGN_CHAT_SESSION,
                "error": safe_assignment_text(str(exc), limit=320),
                "persona_id": persona_id,
                "session_id": args.session_id,
                "next_expected": "open the instance that owns this chat session, or start a fresh thread",
            }
            _emit_persona_verb_payload(args, data)
            return 2
    except RetiredPersonaInstanceError as exc:
        data = _retired_persona_instance_payload(exc)
        _emit_persona_verb_payload(args, data)
        return 2
    except (ValueError, OSError) as exc:
        _emit_persona_verb_payload(args, {"ok": False, "error": str(exc)})
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
        _emit_persona_verb_payload(args, data)
        return 2
    try:
        _ensure_persona_chat_session(
            session_db=_instance_session_db(instance),
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
        _emit_persona_verb_payload(args, data)
        return 2
    # Placed AFTER the transcript row is durable (the ensure above) so the warm
    # can read the root's native tip and revision — the two values that decide
    # whether the first turn REUSES the actor or rebuilds it. See the helper.
    _prewarm_chat_actor_for_open(instance.default_chat_session_id)
    previous_session_id, instance_updated_at, binding_changed = _binding_change(
        previous_instance, instance
    )
    data = {
        "ok": True,
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "profile_id": instance.profile_id,
        "mode": instance.mode,
        "default_chat_session_id": instance.default_chat_session_id,
        "session_id": instance.default_chat_session_id,
        **({"client_scope": args.client_scope} if getattr(args, "client_scope", None) is not None else {}),
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
        # The instance a ``--move`` took this chat from; null when nothing moved.
        "moved_from_persona_instance_id": moved_from,
        "add_instance": False,
        "display_name": instance.display_name,
        "placement_id": None,
        "coordinator_permission_scope": asdict(coordinator_scope) if coordinator_scope is not None else None,
        "next_expected": "resume or send on this chat session to boot the persona instance history",
    }
    _emit_persona_verb_payload(
        args,
        data,
        plain=f"opened {instance.id} on chat {instance.default_chat_session_id}",
    )
    return 0


def _move_target(args, owner_instance, persona_ok, target_instance_id, session_owner) -> str | None:
    """``--move`` (owner 2026-11-19, "Reuse idle, else new"): the instance a saved
    chat of ANOTHER instance of the same agent moves onto, or ``None`` (no move;
    the ownership fence then refuses a foreign chat as before). A different
    agent's chat never moves: here (``persona_ok``) and in the move lane."""

    if not (bool(getattr(args, "move", False)) and owner_instance is not None and persona_ok):
        return None
    return target_instance_id if target_instance_id and target_instance_id != session_owner else None


def _bind_for_open(args, session_db, move_to, persona_id, target_instance_id):
    """``(bound instance, the instance a move took the chat from)``, or a printed refusal's exit code."""

    if move_to is None:
        instance = PersonaInstanceStore().open_chat(
            persona_id=persona_id,
            persona_instance_id=target_instance_id,
            session_id=args.session_id,
            correlation_id=getattr(args, "correlation_id", None),
        )
        return instance, None
    moved = _move_chat_for_open(args, session_db, move_to, persona_id)
    return moved if isinstance(moved, int) else (moved.instance, moved.moved_from)


def _move_chat_for_open(args, session_db, move_to: str, persona_id: str):
    """``--move``: the move lane's answer, or the exit code of the refusal it printed."""

    from agent_runtime.mission_chat_outcome import ChatErrorKind
    from agent_runtime.persona_chat_continuity import PersonaChatBusyError
    from agent_runtime.persona_chat_move import ChatMoveRefused, move_chat

    try:
        return move_chat(
            session_db=session_db,
            session_id=args.session_id,
            to_instance_id=move_to,
            requested_by=getattr(args, "requested_by", None),
            correlation_id=getattr(args, "correlation_id", None),
        )
    except ChatMoveRefused as exc:
        return _emit_persona_open_chat_error(
            args, error_kind=exc.error_kind, error=exc.error, persona_id=persona_id,
            persona_instance_id=move_to, next_expected=exc.next_expected,
        )
    except PersonaChatBusyError as exc:
        return _emit_persona_open_chat_error(
            args, error_kind=ChatErrorKind.CHAT_BUSY, error=str(exc), persona_id=persona_id,
            persona_instance_id=move_to,
            next_expected="wait for the reply in this chat to finish, then open it again",
        )


def _persona_instance_updated_at(instance) -> str | None:
    if instance is None:
        return None
    value = getattr(instance, "updated_at", None)
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return safe_assignment_text(value, limit=80) or None


def _unplaced_agent_named_by(instance_id: str | None, persona_id: str) -> str | None:
    """The agent ``persona_id`` when ``instance_id`` is its bare id with no row under it; else ``None``.

    A profile's own channel keeps its id (documented edge), and another agent's bare id is not this open's
    to place: the ownership fence answers that one."""

    hidden = _unplaced_hidden_copy_persona(instance_id, persona_id) if instance_id else None
    return hidden if hidden is not None and personas_equal(hidden, persona_id) else None


def _place_for_bare_open(args, persona_id: str) -> str | int:
    """The instance a bare open lands on: the agent's idle instance in the Default workspace (its live chat
    is then replaced by the one selected, and nothing is announced), else a newly placed one (whose
    placement announces ``persona_instance.created``). A refused placement answers ``agent_not_placed``
    and returns the exit code."""

    from agent_runtime.agent_create.staff import reuse_or_place

    placed, refusal = reuse_or_place(persona_id)
    if refusal is None:
        return placed
    # MUTATION: answer foreign_chat_session here and test_a_bare_open_whose_placement_is_refused_says_it_is_not_placed reddens.
    refused = AgentNotPlacedError(persona_id, persona_instance_id_for(persona_id))
    return _emit_persona_open_chat_error(
        args, error_kind=refused.code,
        error=f"{persona_id} is not placed in a workspace and could not be placed: {refusal['message']}",
        persona_id=persona_id, persona_instance_id=refused.persona_instance_id,
        next_expected="place the agent in a workspace (runtime.agent.place), then open its chat")


def _unplaced_hidden_copy_persona(instance_id: str, persona_id: str) -> str | None:
    """The agent whose hidden-copy id ``instance_id`` is, when no row is under it; else ``None``.

    The agent is the one the caller named, or the one the id names (``personainst_<persona>``): a
    client may send its own spelling of the agent beside the id (``persona:base``). A row that exists
    under the id (adopted, or a profile's own held channel) is opened as itself.

    A profile agent's channel ``personainst_profile_<name>`` with no row under it is that agent's too,
    when the roster holds the agent (profile discovery's ``profile_base`` on a fresh account namespace,
    where Base is a template only): nothing mints that channel for a new chat, so its open places the
    agent like any other (Eternia row
    MC-FU-A-CHAT-CAN-BE-STARTED-ON-YOUR-PHONES-AGENT-FROM-THE-PHONE-AND-FROM-YOUR-COMPUTER, seen live
    2026-11-26: "persona instance not found: personainst_profile_base"). A profile the roster does not
    hold (a synthesised one) is not placeable and stays not found."""

    from agent_runtime import paths

    named = {persona_id}
    if instance_id.startswith("personainst_"):
        named.add(instance_id[len("personainst_"):])
    for candidate in sorted(p for p in named if p):
        if instance_id == persona_instance_id_for(candidate):
            if paths.persona_instance_path(instance_id).exists():
                return None
            # MUTATION: return None here for every profile_ candidate and
            # test_a_new_chat_on_a_profile_agent_with_no_channel_places_it reddens (persona_instance_not_found).
            if candidate.startswith("profile_"):
                return candidate if _an_agent_this_runtime_has(candidate) else None
            # An id only the id names is a hidden copy only of an agent this runtime has: an unknown instance
            # ``personainst_qa_deadbeef`` of ``qa`` is not agent ``qa_deadbeef``'s hidden copy, and opening it
            # is ``persona_instance_not_found`` naming that id, never a placement of an agent that does not exist
            # (hermes row RT-FU-SEVEN-MORE-AGENT-RUNTIME-TEST-FILES-RED-ON-MAIN-ON-WINDOWS).
            # MUTATION: drop this check and test_serve_rpc_open_chat's
            # test_an_unknown_instance_is_not_found_rather_than_invented reddens (no persona_instance_id).
            if candidate != persona_id and not _an_agent_this_runtime_has(candidate):
                return None
            return candidate
    return None


def _an_agent_this_runtime_has(persona_id: str) -> bool:
    """Whether the persisted roster holds ``persona_id``; an unreadable roster answers yes (the open decides)."""

    from agent_runtime.agent_create.outcome import PersonaRosterUnavailable
    from agent_runtime.agent_create.request import persona_roster

    try:
        roster = persona_roster()
    except PersonaRosterUnavailable:
        return True
    return any(getattr(persona, "id", None) == persona_id for persona in roster)


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

    target_instance_id, persona_id, refused = _new_chat_target(args, persona_id)
    if refused is not None:
        return refused
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
        with closing(_instance_session_db(current)) as session_db:
            receipt = mint_chat_root(
                instance_store=store,
                session_db=session_db,
                persona_id=persona_id,
                persona_instance_id=target_instance_id,
                idempotency_key=getattr(args, "idempotency_key", None),
                # A caller that needs the root BEFORE its turn (the Lens forge)
                # names it here, at the mint, rather than re-titling after.
                title=(safe_assignment_text(getattr(args, "title", None), limit=120)
                       or f"{current.display_name} chat"),
                select=getattr(args, "select_session", True),
                client_scope=getattr(args, "client_scope", None),
            )
    except ConversationOwnerError as exc:
        return _emit_persona_open_chat_error(
            args, error_kind=exc.reason, error="This conversation could not be reopened.",
            persona_id=persona_id, persona_instance_id=target_instance_id)
    except PersonaChatMintError as exc:
        return _emit_persona_open_chat_error(
            args,
            error_kind=exc.code,
            error=str(exc),
            persona_id=persona_id,
            persona_instance_id=target_instance_id,
        )
    except RetiredPersonaInstanceError as exc:
        data = _retired_persona_instance_payload(exc)
        data.update(_mint_receipt_fields(exc))
        _emit_persona_verb_payload(args, data)
        return 2
    except PersonaChatPersistenceError as exc:
        data = {
            "ok": False,
            "error_kind": ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
            "persistence_operation": exc.operation,
            "error": str(exc),
            "persona_id": persona_id,
            "persona_instance_id": target_instance_id,
            **_mint_receipt_fields(exc),
            "next_expected": "restore canonical persona chat transcript storage and retry with the same idempotency key",
        }
        _emit_persona_verb_payload(args, data)
        return 2
    instance = receipt.instance

    # The highest-value prewarm in the harness: a freshly minted root has no
    # turn that is not its first, so without this EVERY new chat pays the cold
    # construction on the operator's opening message. The mint is bound and the
    # transcript row is durable by this line.
    _prewarm_chat_actor_for_open(receipt.session_id)
    data = _new_chat_opened_payload(receipt, coordinator_scope)
    _emit_persona_verb_payload(
        args,
        data,
        plain=f"opened {instance.id} on new chat {receipt.session_id}",
    )
    return 0


def _new_chat_target(args, persona_id: str) -> tuple[str | None, str, int | None]:
    """``(target instance id, persona id, None)`` for a new chat's open, or ``(None, persona id,
    exit code)`` when the open was refused and its error emitted."""
    from agent_runtime.mission_chat_outcome import ChatErrorKind

    requested_instance_id = safe_assignment_token(
        getattr(args, "persona_instance_id", None)
    )
    hidden_copy_of = _unplaced_hidden_copy_persona(
        canonical_persona_instance_id(requested_instance_id, persona_id=persona_id), persona_id,
    ) if requested_instance_id else None
    if hidden_copy_of is not None:
        # A client that still names the agent's hidden copy ``personainst_<persona>`` (Eternia's template
        # console, seen live 2026-11-21 w1118a-mint: "persona instance not found: personainst_base") means
        # the agent: nothing mints that row any more (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT),
        # so its open runs the bare-agent rule below. A row that exists under that id is still opened.
        # MUTATION: drop this test and test_an_open_naming_a_missing_hidden_copy_places_the_agent reddens.
        requested_instance_id, persona_id = None, hidden_copy_of
    if requested_instance_id:
        target_instance_id = canonical_persona_instance_id(requested_instance_id, persona_id=persona_id)
    elif persona_id.startswith("profile_") and hidden_copy_of is None:
        # A profile's channel (documented edge); one with no row under it was answered above as the agent.
        # MUTATION: drop ``and hidden_copy_of is None`` and
        # test_a_new_chat_on_a_profile_agent_with_no_channel_places_it reddens (the channel id again).
        target_instance_id = persona_instance_id_for(persona_id)
    else:
        # RT-A-SEND-TO-AN-AGENT-WITH-NO-INSTANCE-IN-REACH-IS-PLACED-OR-REFUSED: an operator's open that
        # names only the agent runs the one "reuse idle, else place in the Default workspace" rule,
        # never the hidden copy ``personainst_<persona>``.
        # MUTATION: answer persona_instance_id_for here and test_an_operator_open_of_an_unplaced_agent_places_it reddens.
        from agent_runtime.agent_create.staff import reuse_or_place
        from agent_runtime.persona_chat_mints import _validated_key

        # The mint's own key check, asked BEFORE anything is placed, so a refused open leaves no
        # instance behind (seen in the lane's CLI read: an open with no key placed one, then refused).
        # MUTATION: drop this check and test_a_refused_open_places_nothing reddens.
        try:
            _validated_key(getattr(args, "idempotency_key", None))
        except PersonaChatMintError as exc:
            return None, persona_id, _emit_persona_open_chat_error(
                args, error_kind=exc.code, error=str(exc), persona_id=persona_id
            )
        target_instance_id, refusal = reuse_or_place(persona_id)
        if refusal is not None:
            return None, persona_id, _emit_persona_open_chat_error(
                args, error_kind=ChatErrorKind.PERSONA_INSTANCE_NOT_FOUND,
                error=f"no instance of {persona_id!r} could be placed: {refusal['message']}",
                persona_id=persona_id,
                next_expected="place the agent in a workspace (runtime.agent.place), then open its chat",
            )
    return target_instance_id, persona_id, None


def _new_chat_opened_payload(receipt, coordinator_scope) -> dict:
    """The open's success payload: the minted root, its selection and the coordinator scope."""
    instance = receipt.instance
    selected = receipt.selected
    data = {
        "ok": True,
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "mode": instance.mode,
        "session_id": receipt.session_id,
        "mission_chat_root_id": receipt.session_id,
        "chat_busy": False,
        "add_instance": False,
        "new_session": True,
        "selected": selected,
        "selection_requested": receipt.select_session,
        "superseded": receipt.select_session and not selected,
        "idempotent_replay": receipt.idempotent_replay,
        "mint_receipt_state": receipt.state,
        **({"client_scope": receipt.client_scope} if receipt.client_scope is not None else {}),
        "coordinator_permission_scope": asdict(coordinator_scope)
        if coordinator_scope is not None
        else None,
        "next_expected": "resume or send on this server-minted chat root",
    }
    return data


def _mint_receipt_fields(exc) -> dict:
    """The root a same-key retry resolves, when the refusal came after the reservation."""
    receipt = getattr(exc, "mint_receipt", None)
    if receipt is None:
        return {}
    return {
        "session_id": receipt.session_id,
        "mission_chat_root_id": receipt.session_id,
        "idempotent_replay": receipt.idempotent_replay,
        "mint_receipt_state": receipt.state,
    }


def _binding_change(previous_instance, instance) -> tuple[str | None, str | None, bool]:
    """``(previous_session_id, instance_updated_at, changed)`` for the binding receipt."""
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
    return previous_session_id, instance_updated_at, binding_changed


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
        from agent_runtime.launcher_app_functions import current_launcher_link
        from agent_runtime.persona_chat_actor_prewarm import request_chat_actor_prewarm

        # The connection the gesture came in on, when the serve bound one: the
        # prewarm registers its app functions first (h-chatperf), so it builds
        # the tool contract the chat's first turn will build.
        request_chat_actor_prewarm(session_id, launcher_link=current_launcher_link())
    except Exception:
        pass


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
    _emit_persona_verb_payload(args, data)
    return 2
