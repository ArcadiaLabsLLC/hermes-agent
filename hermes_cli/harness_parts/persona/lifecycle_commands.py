"""Instance lifecycle verbs: ``persona instance create``, and the retire outcome.

Separate because these mint or retire identities; the console-denial mirror and
the retire-outcome mapping the instance verbs share live here. ``agent create``
and ``agent retire`` were deleted as argv verbs on 2026-10-02 (owner ruling: the
launcher reaches them only as ``runtime.agent.create`` / ``runtime.agent.retire``,
and no operator or script uses the argv form).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from agent_runtime.call_authorization import CLI_CONSOLE
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    RetiredPersonaInstanceError,
    normalize_persona_or_template_id as _normalize_cli_persona_or_template_id,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError,
    default_persona_session_db as _default_persona_session_db,
    ensure_persona_chat_session as _ensure_persona_chat_session,
    persona_session_db_for,
)
from agent_runtime.chat_heads import resolve_conversation_chat_scope
from .chat_coordinator import (
    _coordinator_actor_id,
    _coordinator_confirm_payload,
    _coordinator_spawn_scope,
    _maybe_stamp_spawned_by,
)
from .chat_request import _emit_persona_verb_payload, _retired_persona_instance_payload
from .chat_target import _persona_by_id

__layer__ = "lanes"
__all__ = [
    "_agent_retire_outcome",
    "_cmd_persona_instance_create",
    "_console_denial",
]


def _console_denial(action: str) -> dict | None:
    """The CLI's half of the front-door gate. ``None`` when the call may run.

    The MIRROR of ``serve_rpc.handle_request``'s check (chokepoint plan, Ruling
    A option (b)), evaluated by the same predicate against the same tier
    vocabulary, so the CLI and RPC doors onto ``perform_agent_retire`` cannot
    answer differently.

    The identity is a CONSTANT — ``CLI_CONSOLE`` — and takes nothing off the
    invocation. That is the whole point: an argv-derived identity is what
    ``coordinator_permissions`` already is, and rebuilding it here would put a
    self-declaration at the one door the machine owner types into. The operator
    at their own shell IS the console; there is nothing to prove and nothing to
    read.

    So today this returns ``None`` unconditionally, and that is honest rather
    than vestigial: it is the grandfather clause §2 of the plan names, spelled as
    a call so it is greppable, so the retire door provably carries it, and so the
    day a non-console CLI identity exists (a sudo-less service account, a
    delegated shell) the refusal is a predicate edit and not a new concept.

    The refusal it WOULD render is shaped as the retire service's own refusal
    kwargs, so the CLI envelope prints it through the arm it already has for a
    refused retire.
    """

    from agent_runtime.call_authorization import (
        CLI_CONSOLE,
        TIER_CONSOLE,
        authorize_call,
    )
    from agent_runtime.serve_rpc.protocol import ERR_HANDLER_FAILED

    decision = authorize_call(TIER_CONSOLE, CLI_CONSOLE)
    if decision.ok:
        return None
    return {
        "code": ERR_HANDLER_FAILED,
        "message": f"{action} requires the {decision.tier} tier",
        "data": {
            **decision.refusal_data(),
            "next_expected": (
                "run this verb from an operator console on the install that owns "
                "this runtime root"
            ),
        },
    }


def terminal_request_actor(requested_by: object = None) -> str:
    """Who asked at a CLI removal door: the agent whose terminal runs it, else the named, else you.

    An agent's terminal tool exports its turn's ``HERMES_SESSION_ID`` (``tools.environments.local.
    _inject_session_context_env``), so the session decides — through ``request_actor``, the one
    owner of "who asked" — and an agent's own ``--requested-by`` never overrides it (review
    w1118a.61 D7). The operator's shell carries no agent session and records ``operator``.
    """

    from agent_runtime.request_actor import request_actor
    from gateway.session_context import get_session_env

    return request_actor(requested_by, caller=CLI_CONSOLE, session=get_session_env("HERMES_SESSION_ID"))


def _agent_retire_outcome(args):
    """The ONE retire the CLI performs: ``harness persona instance retire``'s.

    It calls ``agent_retire.perform_agent_retire`` — the same function
    ``runtime.agent.retire`` answers with — so a lane switch is not a behaviour
    change and the ack is IDENTICAL down to the key order. ``harness agent
    retire`` was a second argv door onto this function until 2026-10-02, when it
    was deleted (owner ruling: method-only on the launcher, no operator or script
    use); the persona-instance verb keeps its own envelope and its coordinator
    gate.

    ``correlation_id`` is read through ``getattr`` with the same ``None``
    default as its siblings, so an operator who does not type the flag reaches
    the store with no token and gets the ack they always got.

    **The authorization identity is minted here** (chokepoint plan A4-ii/iii):
    ``CLI_CONSOLE``, evaluated by the same predicate the RPC front door uses.
    The coordinator gate answers a different question (see
    ``agent_runtime.coordinator_permissions``) and only recognises
    ``--requested-by coordinator``. Today the console check always allows — the
    operator at the machine's own shell IS the console — and that is the
    grandfather clause, made greppable instead of implicit in an absent check.

    The verb publishes ``--correlation-id`` (S8b-b): the launcher's
    ``persona.instance.retire`` argv capability is this door, fired from
    ``MissionOfficeLayoutController.retireAgent``'s ``Unavailable`` arm, whose
    ``correlationId`` is REQUIRED — so the token must survive the arm that runs
    when the RPC lane is degraded, which is when a grep over the event log is
    the only join an operator has.
    """

    from agent_runtime.agent_retire import AgentRetireOutcome, AgentRetireRefusal
    from agent_runtime.agent_retire import perform_agent_retire

    denial = _console_denial("runtime.agent.retire")
    if denial is not None:
        return AgentRetireOutcome(refusal=AgentRetireRefusal(**denial))

    return perform_agent_retire(
        {
            "persona_instance_id": getattr(args, "persona_instance_id", None),
            "reason": getattr(args, "reason", None),
            "requested_by": terminal_request_actor(getattr(args, "requested_by", None)),
            "correlation_id": getattr(args, "correlation_id", None),
        },
        # Stage A6's backstop gets this door's identity too — the SAME constant
        # the gate above evaluated, minted in this one function so the two
        # retire doors cannot drift apart a second time.
        caller=CLI_CONSOLE,
    )


def _instance_session_db(instance):
    """THE writer for *instance*'s own chat head: the create's root and the new-chat mint.

    Acquired through the one conversation resolver, so a never-bound instance (no
    chat pointer, no recorded head) writes where its first bind will stamp the head
    (``chat_heads.first_bind_chat_head``) and the send and the model read find the
    root there (RT-FU-A-NEW-CHAT-WITH-AN-AGENT-ON-ITS-OWN-PROFILE-CANNOT-TAKE-ITS-FIRST-MESSAGE:
    the mint asked ``resolve_instance_chat_scope``, which has no first-bind rule, and
    wrote Neko's new chat into ``profiles/base``). A bound instance gets the answer
    ``resolve_instance_chat_scope`` gives, unchanged.
    """

    return persona_session_db_for(
        resolve_conversation_chat_scope(instance=instance), process=_default_persona_session_db
    )


def _owner_refusal_reason(exc: BaseException) -> str | None:
    """``conversation_owner_changed`` when a chat write was refused for its owner.

    The durability helper wraps every failure as a persistence error; a chat
    another account (or no account) already owns is a refusal, not a storage
    fault, so it keeps its own reason.
    """

    from agent_runtime.conversation_owner import ConversationOwnerError

    cause = exc.__cause__
    return cause.reason if isinstance(cause, ConversationOwnerError) else None


def _cmd_persona_instance_create(args) -> int:
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.agent_create import require_known_persona
    from agent_runtime.agent_create.outcome import AGENT_CREATE_REFUSED_REASON
    from agent_runtime.conversation_owner import ConversationOwnerError, client_scope as _valid_client_scope
    from agent_runtime.mission_chat_outcome import ChatErrorKind
    # RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT: the account the new chat
    # belongs to, validated before anything is written; ``None`` keeps the
    # operator (unscoped) behaviour for local callers.
    try:
        owner = _valid_client_scope(getattr(args, "client_scope", None))
    except ConversationOwnerError as exc:
        _emit_persona_verb_payload(args, {"ok": False, "error_kind": exc.reason, "error": "Invalid conversation owner."})
        return 2
    display_name = safe_assignment_text(getattr(args, "display_name", None), limit=120)
    add_instance = bool(getattr(args, "add_instance", False))
    # Owner 2026-11-19 (RT-PLACING-A-SHIPPED-AGENT-MAKES-A-SECOND-ONE): only an
    # explicit ``--independent-agent`` makes a new agent. ``--add-instance`` alone
    # PLACES the existing one: one more instance, no new persona or profile.
    independent = bool(getattr(args, "independent_agent", False))
    cfg = load_agent_runtime_config()
    persona_id = _normalize_cli_persona_or_template_id(args.persona_id)
    persona = _persona_by_id(cfg, persona_id)
    coordinator_id = _coordinator_actor_id(args)
    coordinator_scope, refused = _coordinator_spawn_scope(
        "persona.instance.create", coordinator_id, spawns=bool(display_name or add_instance))
    if refused is not None:
        _emit_persona_verb_payload(args, refused, plain=refused["message"])
        return 2
    # UC-H4. Until now this handler minted a roster row and a chat root for any
    # id that TOKENISED — `--persona qa_agent` against a roster of
    # base/backend_dev/dev/neko_supervisor/qa produced durable artifacts bound
    # to nothing, and `_persona_by_id` returning None went unchecked three
    # lines above. Fail-open becomes fail-closed for that class only; the
    # `profile:` carve-out (D-U1) and every roster-sourced caller are
    # untouched, and the refusal is the SAME spelling the unified lane uses.
    #
    # Asked AFTER the coordinator gate on purpose: an unauthorised actor should
    # be told it is unauthorised, not handed a roster probe. Both refusals are
    # still before any store write.
    refusal = require_known_persona(persona_id, persona)
    if refusal is not None:
        _emit_persona_verb_payload(args, refusal)
        return 2
    if add_instance or independent:
        # RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT: placing and copying
        # are ``agent_create.perform``'s, the sequence ``runtime.agent.place`` /
        # ``runtime.agent.create`` run — its reservation, name lock and seat.
        # MUTATION: send --add-instance back to ``PersonaInstanceStore().add_instance``
        # and test_the_cli_create_flags_lower_to_the_one_sequence[add_instance-perform_agent_place] reddens.
        return _place_or_make_through_agent_create(
            args, persona_id=persona_id, persona=persona, independent=independent, display_name=display_name,
            owner=owner, coordinator_id=coordinator_id, coordinator_scope=coordinator_scope,
        )
    if display_name:
        target_instance_id = None
        if not persona_id.startswith("profile_"):
            # RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT: the chat opens on an instance placed by the
            # one "reuse idle, else place in the Default workspace" rule, never on a hidden copy.
            # MUTATION: skip this and test_the_cli_operator_chat_opens_on_a_placed_instance reddens.
            from agent_runtime.agent_create.staff import reuse_or_place

            target_instance_id, place_refusal = reuse_or_place(persona_id)
            if place_refusal is not None:
                _emit_persona_verb_payload(args, {"ok": False, "error_kind": AGENT_CREATE_REFUSED_REASON,
                                                  "error": place_refusal["message"]})
                return 2
        try:
            instance = PersonaInstanceStore().create_operator_chat(
                persona_id=persona_id,
                display_name=display_name or safe_assignment_text(args.title, limit=120) or persona_id,
                session_id=getattr(args, "session_id", None),
                client_scope=owner,
                persona_instance_id=target_instance_id,
            )
            if coordinator_id:
                instance = _maybe_stamp_spawned_by(instance, coordinator_id=coordinator_id)
        except RetiredPersonaInstanceError as exc:
            data = _retired_persona_instance_payload(exc)
            _emit_persona_verb_payload(args, data)
            return 2
        except (ValueError, OSError) as exc:
            _emit_persona_verb_payload(args, {"ok": False, "error_kind": AGENT_CREATE_REFUSED_REASON, "error": str(exc)})
            return 2
        except PersonaChatPersistenceError as exc:
            # The mint itself now refuses rather than binding a root it could not
            # persist, so this frame arrives from INSIDE the store. Same shape as
            # the post-bind one below; there is simply no instance yet to name.
            data = {
                "ok": False,
                "error_kind": _owner_refusal_reason(exc) or ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
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
                client_scope=owner,
            )
        except PersonaChatPersistenceError as exc:
            data = {
                "ok": False,
                "error_kind": _owner_refusal_reason(exc) or ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
                "persistence_operation": exc.operation,
                "error": str(exc),
                "persona_id": instance.persona_id,
                "persona_instance_id": instance.id,
                "session_id": instance.default_chat_session_id,
                "next_expected": "restore canonical persona chat transcript storage and retry",
            }
            _emit_persona_verb_payload(args, data)
            return 2
        data = _instance_created_reply(instance, owner=owner, coordinator_scope=coordinator_scope)
        _emit_persona_verb_payload(args, data, plain=f"created {instance.id} on chat {instance.default_chat_session_id}")
        return 0
    return _retired_assignment_lane_refusal(args, persona_id)


def _instance_created_reply(instance, *, owner, coordinator_scope) -> dict:
    """The ``persona instance create`` reply for a minted operator chat channel."""

    return {
        "ok": True,
        "agent_profile_id": instance.id,
        "persona_instance_id": instance.id,
        "source_persona_id": instance.persona_id,
        "persona_id": instance.persona_id,
        "source_profile_id": instance.profile_id,
        "profile_id": instance.profile_id,
        "agent_profile_display_name": instance.display_name,
        "display_name": instance.display_name,
        "lifecycle_mode": instance.mode,
        "mode": instance.mode,
        "default_chat_session_id": instance.default_chat_session_id,
        "chat_session_id": instance.default_chat_session_id,
        "session_id": instance.default_chat_session_id,
        "chat_busy": False,
        "add_instance": False,
        "placement_id": None,
        **({"client_scope": owner} if owner is not None else {}),
        "coordinator_permission_scope": asdict(coordinator_scope) if coordinator_scope is not None else None,
        "next_expected": "agent profile created; refresh Harness snapshot for the profile, chat, and scene placement state",
    }


def _place_or_make_through_agent_create(args, *, persona_id: str, persona, independent: bool, display_name: str,
                                       owner, coordinator_id, coordinator_scope) -> int:
    """``--add-instance`` / ``--independent-agent``: the argv twin of ``runtime.agent.place`` /
    ``runtime.agent.create``, through the one sequence (``agent_create.perform``).

    ``--add-instance`` places one more instance of the EXISTING agent in ``--workspace-id``;
    ``--independent-agent`` makes a NEW agent (seated when a workspace is named). The service
    answers and refuses exactly as the method does; this door only maps argv onto its params,
    stamps who asked, and prints the row. ``--client-message-id`` is the idempotency key (a
    retry converges on one agent); without one, every call is its own key.
    """

    from agent_runtime.agent_create import perform_agent_create, perform_agent_place

    if safe_assignment_text(getattr(args, "session_id", None), limit=200):
        _emit_persona_verb_payload(args, {
            "ok": False, "error_kind": "invalid_request",
            "error": "--session-id is not taken with --add-instance or --independent-agent: "
                     "a placed or new agent starts on its own chat",
        })
        return 2
    key = safe_assignment_text(getattr(args, "client_message_id", None), limit=200) or f"argv-{uuid.uuid4().hex}"
    params = {
        name: value for name, value in {
            "persona_id": persona_id,
            "display_name": display_name or None,
            "workspace_id": safe_assignment_token(getattr(args, "workspace_id", None)) or None,
            "realm_id": safe_assignment_token(getattr(args, "realm_id", None)) or None,
            "placement_id": safe_assignment_token(getattr(args, "placement_id", None)) or None,
            "client_scope": owner,
            "idempotency_key": key,
            "correlation_id": getattr(args, "correlation_id", None),
        }.items() if value is not None
    }
    asker = coordinator_id or "operator"
    if independent:
        source = safe_assignment_token(getattr(args, "source_instance_id", None))
        outcome = perform_agent_create({**params, **({"source_instance_id": source} if source else {})},
                                       persona=persona)
    else:
        outcome = perform_agent_place(params, persona=persona, requested_by=asker)
    if outcome.refusal is not None:
        refusal = outcome.refusal
        data = {**refusal.data, "ok": False, "error_kind": refusal.data.get("reason"), "error": refusal.message}
        _emit_persona_verb_payload(args, data, plain=refusal.message)
        return 2
    result = dict(outcome.result or {})
    if independent and coordinator_id and result.get("persona_instance_id"):
        _maybe_stamp_spawned_by(PersonaInstanceStore().get(result["persona_instance_id"]),
                                coordinator_id=coordinator_id)
    session_id = result.get("default_chat_session_id")
    data = {
        **result,
        "ok": True,
        "agent_profile_id": result.get("persona_instance_id"),
        "session_id": session_id,
        "chat_session_id": session_id,
        "add_instance": not independent,
        "independent_agent": independent,
        **({"client_scope": owner} if owner is not None else {}),
        "coordinator_permission_scope": asdict(coordinator_scope) if coordinator_scope is not None else None,
        "next_expected": "send on session_id with `harness mission-chat message`" if session_id else
                         "the agent has no instance until it is placed: its first chat places it",
    }
    plain = (f"created {data['agent_profile_id']} on chat {session_id}" if session_id else
             f"created agent {result.get('persona_id')} (a template: no instance until it is placed)")
    _emit_persona_verb_payload(args, data, plain=plain)
    return 0


def _retired_assignment_lane_refusal(args, persona_id: str) -> int:
    # S70: the display-name-less branch used to queue a "free-floating persona
    # assignment" (and optionally auto-run one bounded turn beside the canonical
    # chat lane). The queue's only durable consumer was the tick loop the
    # 2026-07-30 chat-only purge removed — a queued row dead-ended forever, the
    # advertised `persona instance run-once` follow-up verb never existed, and
    # the auto-run turn was a second, parallel turn authority beside
    # `mission-chat message`. The lane is retired; refuse loudly instead of
    # silently minting work nothing will ever pick up.
    data = {
        "ok": False,
        "error": (
            "persona instance create requires --display-name (an Agent Profile "
            "or placement mint); the free-floating assignment lane is retired"
        ),
        "persona_id": persona_id,
        "next_expected": (
            "pass --display-name to create the agent profile/placement, then "
            "send messages with `harness mission-chat message`"
        ),
    }
    _emit_persona_verb_payload(args, data)
    return 2
