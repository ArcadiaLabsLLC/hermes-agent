"""Coordinator scope for console verbs, and the ``mission chat steer`` / ``queue-skill`` verbs.

Separate because the coordinator actor, scope and confirm payload are read by
every lane that acts on another agent's behalf.
"""

from __future__ import annotations

from agent_runtime.operator_message import normalize_operator_message

from dataclasses import asdict
from agent_runtime import paths
from agent_runtime.cli_format import emit_json
from agent_runtime.coordinator_permissions import CoordinatorPermissionScope, scope_for_persona
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.models import AgentPersona
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
    "_coordinator_scope_from_args",
    "_maybe_stamp_spawned_by",
]


def _coordinator_actor_id(args) -> str | None:
    raw = str(getattr(args, "requested_by", "") or "").strip()
    if raw.lower().startswith("coordinator:"):
        return safe_assignment_token(raw.split(":", 1)[1])
    if raw.lower() == "coordinator":
        return safe_assignment_token(getattr(args, "coordinator_id", None))
    return None


def _coordinator_scope_from_args(args, cfg, persona: AgentPersona | None) -> CoordinatorPermissionScope:
    scope = scope_for_persona(
        persona,
        config=getattr(cfg, "coordinator_permissions", None),
        spawns_used=int(getattr(args, "coordinator_spawns_used", 0) or 0),
    )
    max_spawns = getattr(args, "coordinator_max_spawns", None)
    if max_spawns is not None:
        scope.max_spawns = max(0, int(max_spawns))
    may_kill_own = getattr(args, "coordinator_may_kill_own", None)
    no_kill_own = getattr(args, "coordinator_no_kill_own", None)
    if may_kill_own is not None:
        scope.may_kill_own = bool(may_kill_own)
    if no_kill_own is not None:
        scope.may_kill_own = not bool(no_kill_own)
    may_kill_others = getattr(args, "coordinator_may_kill_others", None)
    if may_kill_others is not None:
        scope.may_kill_others = bool(may_kill_others)
    return scope


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
        data = submit_mission_chat_steer(
            runtime_root=paths.store_root(),
            session_id=session_id,
            message=message,
            client_message_id=client_message_id,
            persona_id=safe_assignment_token(getattr(args, "persona_id", None)) or None,
            persona_instance_id=safe_assignment_token(getattr(args, "persona_instance_id", None)) or None,
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
