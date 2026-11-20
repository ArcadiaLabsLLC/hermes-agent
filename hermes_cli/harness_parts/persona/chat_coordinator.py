"""Coordinator scope for console verbs, and the ``mission chat steer`` / ``queue-skill`` verbs.

Separate because the coordinator actor, scope and confirm payload are read by
every lane that acts on another agent's behalf.
"""

from __future__ import annotations

from agent_runtime.operator_message import normalize_operator_message

from dataclasses import asdict
from agent_runtime import paths
from agent_runtime.cli_format import emit_json
from agent_runtime.coordinator_permissions import CoordinatorPermissionScope
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    safe_assignment_text,
    safe_assignment_token,
)
from hermes_cli.flag_binding import list_flag_or_empty

__layer__ = "lanes"
__all__ = [
    "_cmd_mission_chat_queue_skill",
    "_cmd_mission_chat_steer",
    "_coordinator_actor_id",
    "_coordinator_confirm_payload",
    "_coordinator_scope",
    "_coordinator_spawn_refusal",
    "_maybe_stamp_spawned_by",
]


def _coordinator_actor_id(args) -> str | None:
    """The coordinator asking at a CLI door: the agent whose terminal runs it, else the one argv names.

    An agent's terminal carries its turn's ``HERMES_SESSION_ID``, so the session decides
    (``terminal_request_actor``, the door removals already read) and nothing the agent types —
    no ``--requested-by``, no ``--coordinator-id`` — changes or drops it (row
    ``RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET``, review w1118a.62
    D1). Only the operator's own shell, which carries no agent session, may name a coordinator.
    """

    from agent_runtime.request_actor import OPERATOR_ACTOR

    from .lifecycle_commands import terminal_request_actor

    # MUTATION: drop this session read and test_an_agents_terminal_add_instance_past_its_budget_is_refused reddens.
    asker = terminal_request_actor()
    if asker != OPERATOR_ACTOR:
        return asker
    raw = str(getattr(args, "requested_by", "") or "").strip()
    if raw.lower().startswith("coordinator:"):
        return safe_assignment_token(raw.split(":", 1)[1])
    if raw.lower() == "coordinator":
        return safe_assignment_token(getattr(args, "coordinator_id", None))
    return None


def _coordinator_scope(coordinator_id: str) -> CoordinatorPermissionScope | None:
    """The scope a coordinator is held to: its agent's settings and its spawns, read from the store.

    ``agent_create.staff.coordinator_scope`` — the one the add-instance tool reads. The five argv
    scope flags (``--coordinator-max-spawns``, ``--coordinator-spawns-used``,
    ``--coordinator-may-kill-own``, ``--coordinator-no-kill-own``, ``--coordinator-may-kill-others``)
    are gone: a caller never grants itself a budget or kill rights (review w1118a.62 D1).
    """

    from agent_runtime.agent_create.staff import coordinator_scope

    return coordinator_scope(coordinator_id)


def _coordinator_spawn_refusal(action: str, coordinator_id: str, auth) -> dict[str, object]:
    """A refused spawn: the confirm payload plus the sentence naming the settings that grant one."""

    from agent_runtime.agent_create.staff import spawn_refusal

    return {**_coordinator_confirm_payload(action, coordinator_id, auth), **spawn_refusal(auth, coordinator_id)}


def _coordinator_confirm_payload(action: str, coordinator_id: str, auth) -> dict[str, object]:
    return {
        "ok": False,
        "status": "needs_operator_confirm",
        "needs_operator_confirm": True,
        "action": action,
        "coordinator_id": coordinator_id,
        "reason": auth.reason,
        "permission_scope": asdict(auth.scope) if auth.scope is not None else None,
        "next_expected": "operator confirmation or a wider coordinator permission scope is required before this warning/destructive action can run",
    }


def _maybe_stamp_spawned_by(instance, *, coordinator_id: str | None, operator_source: str = "operator"):
    source = safe_assignment_token(coordinator_id) if coordinator_id else operator_source
    if not source:
        return instance
    instance.spawned_by = source
    return PersonaInstanceStore().update(instance)


# S70 removed `_cmd_persona_instance_message` and its `persona instance
# message` subparser. The verb queued a "free-floating persona assignment" —
# a row whose only durable consumer was the tick loop the 2026-07-30 chat-only
# purge removed — and its `--auto-run` variant ran a second, parallel chat-turn
# authority beside `mission-chat message`. Messaging an instance is
# `harness mission-chat message`.


def _cmd_mission_chat_steer(args) -> int:
    # Function-local: the convention from before lane H1, when this file was
    # exec'd into harness.py's globals. The turn-outcome vocabulary is owned by
    # agent_runtime.mission_chat_outcome; nothing re-spells its values.
    from agent_runtime.mission_chat_outcome import (
        ChatErrorKind,
        ExecutionState,
    )
    session_id = safe_assignment_text(getattr(args, "session_id", None), limit=200)
    client_message_id = safe_assignment_text(getattr(args, "client_message_id", None), limit=200)
    message = getattr(args, "message", None)
    if not session_id or not client_message_id or not message:
        data = {
            "ok": False,
            "capability_id": "mission.chat.steer",
            "execution_state": ExecutionState.REJECTED,
            "session_id": session_id,
            "client_message_id": client_message_id,
            "error_kind": ChatErrorKind.INVALID_REQUEST,
            "error": "session_id, client_message_id, and non-empty message are required",
        }
        print(emit_json(data) if args.json else data["error"])
        return 2
    try:
        message = normalize_operator_message(message)
        from hermes_cli.harness_parts.serve.queued_turn_origin import send_origin

        data = submit_mission_chat_steer(
            runtime_root=paths.store_root(),
            session_id=session_id,
            message=message,
            client_message_id=client_message_id,
            persona_id=safe_assignment_token(getattr(args, "persona_id", None)) or None,
            persona_instance_id=safe_assignment_token(getattr(args, "persona_instance_id", None)) or None,
            # Who typed it: a steer that arrives too late is answered on that device
            # (RT-LATE-STEER-TYPED-ON-A-PAIRED-DEVICE-IS-NOT-ANSWERED-THERE).
            # MUTATION: drop this argument and test_late_steer_is_an_ordinary_message's device test reddens.
            origin=send_origin(),
        )
    except ValueError as exc:
        data = {
            "ok": False,
            "capability_id": "mission.chat.steer",
            "execution_state": ExecutionState.REJECTED,
            "session_id": session_id,
            "client_message_id": client_message_id,
            "error_kind": ChatErrorKind.INVALID_REQUEST,
            "error": safe_assignment_text(str(exc), limit=240),
        }
        print(emit_json(data) if args.json else data["error"])
        return 2
    print(emit_json(data) if args.json else (data.get("error") or data.get("execution_state") or "accepted"))
    return 0


def _cmd_mission_chat_queue_skill(args) -> int:
    """The argv door; the decision is ``agent_runtime.chat_verbs.queue_skill``."""
    from agent_runtime.chat_verbs.queue_skill import queue_skills_next_turn

    data = queue_skills_next_turn(
        persona_id=getattr(args, "persona_id", None),
        session_id=getattr(args, "session_id", None),
        skills=[*list_flag_or_empty(args, "skill"), *list_flag_or_empty(args, "skills")],
        persona_instance_id=getattr(args, "persona_instance_id", None),
    )
    if data["ok"] is not True:
        print(emit_json(data) if args.json else data["error"])
        return 2
    print(emit_json(data) if args.json else f"queued {', '.join(data['skills'])} for next turn")
    return 0
