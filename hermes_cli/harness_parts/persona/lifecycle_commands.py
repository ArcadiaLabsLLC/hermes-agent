"""Agent and instance lifecycle verbs: ``agent create``, ``agent retire``, ``persona instance create``.

Separate because these mint or retire identities; the console-denial mirror and
the retire-outcome mapping they share with the instance verbs live here.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from agent_runtime.call_authorization import CLI_CONSOLE
from agent_runtime.cli_format import emit_json
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
from agent_runtime.root_observability import attach_root_observability
from hermes_cli.flag_binding import list_flag_or_absent
from .chat_coordinator import (
    _coordinator_actor_id,
    _coordinator_confirm_payload,
    _coordinator_scope_from_args,
    _maybe_stamp_spawned_by,
)
from .chat_request import _retired_persona_instance_payload
from .chat_target import _persona_by_id

__layer__ = "lanes"
__all__ = [
    "_agent_retire_outcome",
    "_cmd_agent_create",
    "_cmd_agent_retire",
    "_cmd_persona_instance_create",
    "_console_denial",
    "_placement_discriminability_refusal",
]


#: UC-H3. The JSON-RPC error-code family, mapped to the harness exit-code
#: taxonomy (2 = bad request, 3 = missing, 4 = conflict, 1 = internal). Keyed on
#: the CODE rather than the reason on purpose: the code family is what the
#: service guarantees, while reasons are added freely and an unmapped one must
#: not silently become exit 0. Note `persona_not_found` therefore exits 2, not
#: the 3 that `ERROR_EXIT_CODES` gives that spelling — it arrives under
#: ERR_INVALID_PARAMS because it is refused by the request normaliser, and the
#: two lanes agreeing about WHY beats either agreeing with a different table.
_AGENT_CREATE_EXIT_CODES = {-32602: 2, 4001: 3, 4090: 4, -32000: 1}


def _cli_create_persona(persona_id: str):
    """The CLI's richer persona resolution, with the RPC lane's typed fault.

    RD-H6 item 2. ``_persona_by_id`` reads the roster through
    ``ensure_persisted_personas`` — the exact call ``agent_create.persona_roster``
    wraps into :class:`PersonaRosterUnavailable`, but UNWRAPPED here, and the
    config load above it is unwrapped too. So a config this process could not
    read left ``harness agent create`` printing a traceback where
    ``runtime.agent.create`` answered a typed ``persona_roster_unavailable``
    refusal naming the runtime as the subject. The fault was identical; only the
    rendering differed, and the argv one blamed nothing and named no cure.

    ``except Exception`` deliberately mirrors :func:`persona_roster`'s own net,
    for the same reason it has one: the roster read reaches YAML parsing, the
    filesystem and the persona store, and enumerating that fault surface here
    would leave the un-enumerated remainder tracebacking — which is the defect.
    It is narrow in SCOPE instead: exactly the roster read, nothing after it.
    A bad id is NOT caught here — ``_persona_by_id`` answers ``None`` for that,
    and the service's ``persona_not_found`` refusal is the one that must answer
    it (collapsing the two would send an operator hunting a typo that does not
    exist, which is the distinction :class:`PersonaRosterUnavailable` exists for).
    """

    from agent_runtime.agent_create import PersonaRosterUnavailable

    try:
        return _persona_by_id(load_agent_runtime_config(), persona_id)
    except Exception as exc:  # noqa: BLE001 — re-raised as the typed fault
        raise PersonaRosterUnavailable(str(exc)) from exc


def _cmd_agent_create(args) -> int:
    """`harness agent create` — one call places an agent.

    The unified door the operator asked for: it calls
    ``agent_create.perform_agent_create``, which is the SAME function
    ``runtime.agent.create`` answers with, so every RESULT field a script reads
    here is the field it would read off the wire — ``position`` and ``actor``
    (plan D2/D11) included, which is what lets a script place an agent WITHOUT
    ``--pos`` and still learn exactly where it went and what row was written. That is the point — a lane
    switch must not be a behaviour change. Two keys are envelope-only and have
    no wire counterpart: ``ok`` (the exit status) and ``resolution`` (the
    root-observability block every ``--json`` harness verb stamps).

    It works with no ``harness serve`` running: every lock in the path (the
    reservation lock, the persona-instance lock, the office lock) is a
    cross-process FILE lock, and the argv fallback lanes already write beside a
    live serve today.

    `--skill` (repeatable) assigns skills to the NEW instance, and is the argv
    twin of the RPC's `skills` param — the service installs and hash-verifies
    every canonical id before it assigns, and refuses rather than handing an
    agent a stale copy. Omitted, the instance inherits its persona's skills.
    A skills refusal keeps the placement: the printed `rolled_back: false` is
    the literal truth there, and re-running with the SAME `--idempotency-key`
    resumes the skills phase alone instead of minting a second agent.

    Why this and not `persona instance create --add-instance`: that verb never
    writes a placement (R#37's shape — there is no office write anywhere in the
    handler), so it leaves a roster row with no desk. It stays as the
    roster-only door; this one is the placement door.
    """

    from agent_runtime.agent_create import (
        PersonaRosterUnavailable,
        perform_agent_create,
        roster_unavailable_outcome,
    )

    try:
        persona_id = _normalize_cli_persona_or_template_id(args.persona_id)
    except ValueError as exc:
        data = {"ok": False, "reason": "persona_id_required", "error": str(exc)}
        print(emit_json(data) if args.json else data["error"])
        return 2

    raw_position = getattr(args, "pos", None)
    position = list(raw_position) if raw_position is not None else None
    if position is not None and len(position) == 2:
        # argparse hands these over as strings; the service refuses anything
        # non-finite, so a bad value stays ONE refusal rather than an
        # argparse traceback here and a typed error there.
        try:
            position = [float(position[0]), float(position[1])]
        except (TypeError, ValueError):
            pass

    params = {
        "persona_id": persona_id,
        "workspace_id": getattr(args, "workspace_id", None),
        "idempotency_key": (
            safe_assignment_text(getattr(args, "idempotency_key", None), limit=240)
            or f"cli-{uuid.uuid4().hex}"
        ),
    }
    # OMITTED, not an explicit ``None`` (plan S2/D2). ``--pos`` is optional now,
    # and the service reads an ABSENT position as "the operator did not aim, let
    # the layout policy choose". Sending ``position: []`` — which this lane did
    # when the flag was required-but-empty — is a malformed aim and refuses
    # ``position_invalid``, so the omission has to reach the service as an
    # omission.
    if position is not None:
        params["position"] = position
    # Same omission rule, one flag over (plan D5). `--skill` absent must reach
    # the service as an ABSENT key: absent leaves `skill_overrides` at `None`
    # (inherit the persona's, live) while `[]` writes an explicit "no skills"
    # override. Sending `skills: []` for an operator who never typed the flag
    # is the exact `None -> []` collapse this slice fixes one handler below.
    requested_skills = list_flag_or_absent(args, "skills")
    if requested_skills is not None:
        params["skills"] = requested_skills
    for key, value in (
        ("display_name", getattr(args, "display_name", None)),
        ("placement_id", getattr(args, "placement_id", None)),
        ("realm_id", getattr(args, "realm_id", None)),
        ("folder", getattr(args, "folder", None)),
        ("correlation_id", getattr(args, "correlation_id", None)),
    ):
        # Omitted stays OMITTED rather than becoming an explicit ``None``: the
        # service distinguishes "no placement_id, mint one" from "a placement
        # id that will not tokenise, refuse".
        if value is not None:
            params[key] = value

    # RD-H6 item 2. The CLI resolves its own richer persona object BEFORE the
    # service runs, so the service's typed roster refusal cannot cover this read
    # — and unwrapped it tracebacked where `runtime.agent.create` answered
    # `persona_roster_unavailable`. Same fault, same reason, both lanes; the
    # refusal falls through to the ONE rendering arm below, so it also inherits
    # the same exit code and the same root-observability envelope.
    # The CLI half of the front-door gate (chokepoint plan A4-ii), the mirror of
    # what `serve_rpc.handle_request` runs for `runtime.agent.create`. Asked
    # BEFORE the roster read for the same reason the coordinator review is asked
    # before it one handler over: a caller who may not place an agent should be
    # told that, not handed a probe of which persona ids exist. Today it always
    # allows — see `_console_denial`.
    denial = _console_denial("runtime.agent.create")
    if denial is not None:
        from agent_runtime.agent_create import AgentCreateOutcome, AgentCreateRefusal

        outcome = AgentCreateOutcome(refusal=AgentCreateRefusal(**denial))
    else:
        try:
            persona = _cli_create_persona(persona_id)
        except PersonaRosterUnavailable as exc:
            outcome = roster_unavailable_outcome(exc)
        else:
            # ``CLI_CONSOLE`` travels INTO the service as well (Stage A6).
            # The door's own gate above is this lane's front door — the mirror
            # of ``handle_request``'s — and the backstop is the second,
            # independent evaluation at the verb itself. Passing the identity
            # rather than letting the service default to it is what makes the
            # door's authority explicit at the call: the default is for callers
            # that have no identity to give.
            outcome = perform_agent_create(
                params, persona=persona, caller=CLI_CONSOLE
            )

    if outcome.refusal is not None:
        refusal = outcome.refusal
        # Root-observability: a create that answered out of the WRONG runtime
        # root refuses just as plausibly as one that answered out of the right
        # one — `persona_not_found` against an empty roster is exactly the
        # well-formed-wrong-answer class the resolution block exists for.
        data = attach_root_observability({
            "ok": False,
            "error": refusal.message,
            **refusal.data,
            "next_expected": (
                "fix the named field and re-run; a refused create wrote nothing "
                "unless it says rolled_back: false"
            ),
        })
        print(emit_json(data) if args.json else data["error"])
        return _AGENT_CREATE_EXIT_CODES.get(refusal.code, 1)

    data = attach_root_observability({"ok": True, **outcome.result})
    print(
        emit_json(data)
        if args.json
        else (
            f"placed {data['persona_instance_id']} as {data['actor_key']} "
            f"on chat {data['default_chat_session_id']}"
        )
    )
    return 0


#: Same family map ``agent create`` uses, over the codes ``agent_retire``
#: answers in. Not re-derived at the call site: an exit code guessed beside a
#: print statement is the second taxonomy this file already retired once.
_AGENT_RETIRE_EXIT_CODES = {-32602: 2, 4001: 3, 4090: 4}


def _console_denial(action: str) -> dict | None:
    """The CLI's half of the front-door gate. ``None`` when the call may run.

    The MIRROR of ``serve_rpc.handle_request``'s check (chokepoint plan, Ruling
    A option (b)), evaluated by the same predicate against the same tier
    vocabulary, so the two doors onto ``perform_agent_create`` /
    ``perform_agent_retire`` cannot answer differently.

    The identity is a CONSTANT — ``CLI_CONSOLE`` — and takes nothing off the
    invocation. That is the whole point: an argv-derived identity is what
    ``coordinator_permissions`` already is, and rebuilding it here would put a
    self-declaration at the one door the machine owner types into. The operator
    at their own shell IS the console; there is nothing to prove and nothing to
    read.

    So today this returns ``None`` unconditionally, and that is honest rather
    than vestigial: it is the grandfather clause §2 of the plan names, spelled as
    a call so it is greppable, so both retire doors provably share it, and so the
    day a non-console CLI identity exists (a sudo-less service account, a
    delegated shell) the refusal is a predicate edit and not a new concept.

    The refusal it WOULD render is shaped as the two service functions' own
    refusal kwargs, so both CLI envelopes print it through the arm they already
    have for a refused create/retire.
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
    """The ONE retire the CLI performs, whichever verb the operator typed.

    ``harness agent retire <id>`` and ``harness persona instance retire <id>``
    are two doors onto ``agent_retire.perform_agent_retire`` — the same function
    ``runtime.agent.retire`` answers with — so a lane switch is not a behaviour
    change and the ack is IDENTICAL down to the key order. The two handlers
    below differ only in their envelope, which is the operator surface each has
    always had, and in the coordinator gate, which is `persona instance`'s.

    ``correlation_id`` is read through ``getattr`` with the same ``None``
    default as its siblings, so an operator who does not type the flag on either
    door reaches the store with no token and gets the ack they always got.

    **The authorization identity is the same on both doors, because it is minted
    here** (chokepoint plan A4-ii/iii). Canon 06 recorded the asymmetry as "one
    retire consults the coordinator gate and the other does not, on the same
    service function" — and the survey found it was worse than an asymmetry: the
    consulted gate never ran either, because it only recognises
    ``--requested-by coordinator`` and the two spellings anyone actually sends
    are ``cli`` (the CLI's own default) and ``launcher``.

    The asymmetry disappears not by giving `agent retire` the coordinator gate —
    that gate answers a different question, see
    ``agent_runtime.coordinator_permissions`` — but because BOTH doors now carry
    ``CLI_CONSOLE``, evaluated by the same predicate the RPC front door uses. It
    is minted in this function rather than in the two handlers precisely so the
    two cannot drift apart a second time: there is one retire, so there is one
    identity.

    Today it always allows — the operator at the machine's own shell IS the
    console — and that is the grandfather clause, made greppable instead of
    implicit in an absent check.

    BOTH doors publish ``--correlation-id``. S8b gave it to `agent retire` alone,
    on the reasoning that only it is the scripted inverse of `agent create
    --correlation-id` and that "no gesture behind it" was the truth for `persona
    instance retire`. That was wrong about its own largest caller: the launcher's
    `persona.instance.retire` argv capability IS this door, fired from
    ``MissionOfficeLayoutController.retireAgent``'s ``Unavailable`` arm, and that
    method takes ``correlationId`` as a REQUIRED parameter. The token therefore
    existed on every launcher retire and was dropped by precisely the arm that
    runs when the RPC lane is degraded — so the create half and the retire half
    of one gesture landed in two correlation spaces on the lane where a single
    grep over the event log is the only join an operator has (S8b-b).
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


def _cmd_agent_retire(args) -> int:
    """`harness agent retire` — one call takes an agent off the level.

    The inverse of `harness agent create`, and its exact twin in shape: it calls
    ``agent_retire.perform_agent_retire``, which is the SAME function
    ``runtime.agent.retire`` answers with, so every RESULT field a script reads
    here is the field it would read off the wire — ``archived_actor_keys`` and
    ``office_archive_failures`` included, which is what lets a script learn
    whether the desk actually left the canvas instead of assuming it did.

    Works with no ``harness serve`` running: every lock in the path is a
    cross-process FILE lock.

    A second retire of the same id is NOT an error — it answers the same ack
    with ``already_retired: true``, so a script that lost its first ack (or a
    cron that runs twice) is idempotent by construction.
    """

    outcome = _agent_retire_outcome(args)

    if outcome.refusal is not None:
        refusal = outcome.refusal
        # Root-observability for the same reason the create carries it: a
        # ``not_found`` answered out of the WRONG runtime root refuses just as
        # plausibly as one answered out of the right one.
        data = attach_root_observability({
            "ok": False,
            "error": refusal.message,
            **refusal.data,
            "next_expected": (
                "a refused retire archived nothing; fix the named condition "
                "(or retire the placement it names) and re-run"
            ),
        })
        print(emit_json(data) if args.json else data["error"])
        return _AGENT_RETIRE_EXIT_CODES.get(refusal.code, 1)

    result = outcome.result
    data = attach_root_observability({"ok": True, **result})
    if args.json:
        print(emit_json(data))
    else:
        keys = ", ".join(result["archived_actor_keys"]) or "no actors"
        failures = result["office_archive_failures"]
        suffix = f" ({len(failures)} office archive failure(s))" if failures else ""
        replay = " (already retired)" if result.get("already_retired") else ""
        print(
            f"retired {result['persona_instance_id']} -> {result['archive_path']}; "
            f"archived {keys}{suffix}{replay}"
        )
    return 0


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
            print(emit_json(data) if args.json else data["status"])
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
        print(emit_json(refusal) if args.json else refusal["error"])
        return 2
    if display_name:
        try:
            if add_instance:
                if not placement_id:
                    data = {"ok": False, "error": "placement_id is required when add_instance is true"}
                    print(emit_json(data) if args.json else data["error"])
                    return 2
                refusal = _placement_discriminability_refusal(placement_id)
                if refusal is not None:
                    print(emit_json(refusal) if args.json else refusal["error"])
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
            print(emit_json(data) if args.json else data["error"])
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
            print(emit_json(data) if args.json else data["error"])
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
            print(emit_json(data) if args.json else data["error"])
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
        print(emit_json(data) if args.json else f"created {instance.id} on chat {instance.default_chat_session_id}")
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
    print(emit_json(data) if args.json else data["error"])
    return 2
