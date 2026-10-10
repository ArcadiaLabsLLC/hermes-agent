"""Instance lifecycle verbs: ``persona instance create``, and the retire outcome.

Separate because these mint or retire identities; the console-denial mirror and
the retire-outcome mapping the instance verbs share live here. ``agent create``
and ``agent retire`` were deleted as argv verbs on 2026-10-02 (owner ruling: the
launcher reaches them only as ``runtime.agent.create`` / ``runtime.agent.retire``,
and no operator or script uses the argv form).
"""

from __future__ import annotations

from dataclasses import asdict
from agent_runtime.call_authorization import CLI_CONSOLE
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.coordinator_permissions import review_coordinator_budget
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
)
from .chat_coordinator import (
    _coordinator_actor_id,
    _coordinator_confirm_payload,
    _coordinator_scope_from_args,
    _maybe_stamp_spawned_by,
)
from .chat_request import _emit_persona_verb_payload, _retired_persona_instance_payload
from .chat_target import _persona_by_id

__layer__ = "lanes"
__all__ = [
    "_agent_retire_outcome",
    "_cmd_persona_instance_create",
    "_console_denial",
    "_placement_discriminability_refusal",
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
            "requested_by": getattr(args, "requested_by", None),
            "correlation_id": getattr(args, "correlation_id", None),
        },
        # Stage A6's backstop gets this door's identity too — the SAME constant
        # the gate above evaluated, minted in this one function so the two
        # retire doors cannot drift apart a second time.
        caller=CLI_CONSOLE,
    )


def _placement_discriminability_refusal(placement_id: str) -> dict | None:
    """R1's fence for the two ``--add-instance`` doors, or ``None`` to proceed.

    These verbs do not pass through ``agent_create``, so the fence there covers
    neither of them; the SHAPE and the SENTENCE still come from the one
    authority in ``agent_runtime.models`` rather than being re-spelled per door.

    Returns a payload rather than raising because both callers already answer
    their own placement refusals this way (``placement_id is required when
    add_instance is true``), and neither catches ``ValueError`` around the
    store call — a raise here would surface as a traceback, not a refusal.
    """

    from agent_runtime.models import (
        PLACEMENT_ID_NOT_DISCRIMINABLE_REASON,
        looks_like_deliberate_placement,
        placement_id_not_discriminable_message,
    )

    if looks_like_deliberate_placement(placement_id):
        return None
    return {
        "ok": False,
        "reason": PLACEMENT_ID_NOT_DISCRIMINABLE_REASON,
        "error": placement_id_not_discriminable_message(placement_id),
        "placement_id": placement_id,
        "next_expected": (
            "re-run without --placement-id to have a discriminable one minted, "
            "or send the <persona-token>_agent_<hex8> shape"
        ),
    }


def _cmd_persona_instance_create(args) -> int:
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.agent_create import require_known_persona
    from agent_runtime.mission_chat_outcome import ChatErrorKind
    display_name = safe_assignment_text(getattr(args, "display_name", None), limit=120)
    kill_active = bool(getattr(args, "kill_active", False))
    add_instance = bool(getattr(args, "add_instance", False))
    placement_id = safe_assignment_token(getattr(args, "placement_id", None))
    cfg = load_agent_runtime_config()
    persona_id = _normalize_cli_persona_or_template_id(args.persona_id)
    persona = _persona_by_id(cfg, persona_id)
    coordinator_id = _coordinator_actor_id(args)
    coordinator_scope = None
    if coordinator_id and (display_name or add_instance):
        coordinator_scope = _coordinator_scope_from_args(args, cfg, persona)
        auth = review_coordinator_budget(
            "persona.instance.create",
            coordinator_scope,
            actor=coordinator_id,
            coordinator_id=coordinator_id,
        )
        if not auth.ok:
            data = _coordinator_confirm_payload("persona.instance.create", coordinator_id, auth)
            _emit_persona_verb_payload(args, data, plain=data["status"])
            return 2
        coordinator_scope = auth.scope
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
    if display_name:
        try:
            if add_instance:
                if not placement_id:
                    data = {"ok": False, "error": "placement_id is required when add_instance is true"}
                    _emit_persona_verb_payload(args, data)
                    return 2
                refusal = _placement_discriminability_refusal(placement_id)
                if refusal is not None:
                    _emit_persona_verb_payload(args, refusal)
                    return 2
                instance = PersonaInstanceStore().add_instance(
                    persona_id=persona_id,
                    placement_id=placement_id,
                    display_name=display_name or safe_assignment_text(args.title, limit=120) or persona_id,
                    session_id=getattr(args, "session_id", None),
                    workspace_id=safe_assignment_token(getattr(args, "workspace_id", None)) or None,
                    realm_id=safe_assignment_token(getattr(args, "realm_id", None)) or None,
                )
            else:
                instance = PersonaInstanceStore().create_operator_chat(
                    persona_id=persona_id,
                    display_name=display_name or safe_assignment_text(args.title, limit=120) or persona_id,
                    session_id=getattr(args, "session_id", None),
                    kill_active=kill_active,
                )
            if add_instance or coordinator_id:
                instance = _maybe_stamp_spawned_by(instance, coordinator_id=coordinator_id)
        except RetiredPersonaInstanceError as exc:
            data = _retired_persona_instance_payload(exc)
            _emit_persona_verb_payload(args, data)
            return 2
        except PersonaChatPersistenceError as exc:
            # The mint itself now refuses rather than binding a root it could not
            # persist, so this frame arrives from INSIDE the store. Same shape as
            # the post-bind one below; there is simply no instance yet to name.
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
            _emit_persona_verb_payload(args, data)
            return 2
        data = {
            "ok": True,
            "agent_profile_id": instance.id,
            "persona_instance_id": instance.id,
            "source_persona_id": instance.persona_id,
            "persona_id": instance.persona_id,
            "source_profile_id": instance.profile_id,
            "agent_profile_display_name": instance.display_name,
            "display_name": instance.display_name,
            "lifecycle_mode": instance.mode,
            "mode": instance.mode,
            "default_chat_session_id": instance.default_chat_session_id,
            "chat_session_id": instance.default_chat_session_id,
            "session_id": instance.default_chat_session_id,
            "chat_busy": False,
            "killed_previous": bool(kill_active),
            "add_instance": add_instance,
            "placement_id": placement_id or None,
            "coordinator_permission_scope": asdict(coordinator_scope) if coordinator_scope is not None else None,
            "next_expected": "agent profile created; refresh Harness snapshot for the profile, chat, and scene placement state",
        }
        _emit_persona_verb_payload(args, data, plain=f"created {instance.id} on chat {instance.default_chat_session_id}")
        return 0
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
