"""Binds the runtime's mission-chat door to the CLI turn handler (ruling Q10).

``agent_runtime.mission_chat_door`` is the slot; this is the CLI side filling
it. The bound callable looks the handler up at CALL time, so a stub on
``chat_turn_message._cmd_mission_chat_message`` still reaches every caller of
the door, as it reached the direct calls the door replaced.

Called from the plugin's ``register`` and from ``ServeSession._boot_and_serve``.
"""

from __future__ import annotations

from agent_runtime.mission_chat_door import (
    CHAT_DELETE_VERB,
    INSTANCE_CREATE_VERB,
    bind_chat_verb,
    bind_mission_chat_turn,
    bind_open_chat,
)

__layer__ = "lanes"
__all__ = ["bind_mission_chat_door"]


def _mission_chat_turn_via_cli(args) -> int:
    from hermes_cli.harness_parts.persona import chat_turn_message

    return chat_turn_message._cmd_mission_chat_message(args)


def _open_chat_via_cli(args) -> int:
    from hermes_cli.harness_parts.persona import chat_open

    return chat_open._cmd_persona_instance_open_chat(args)


def _chat_delete_via_cli(args) -> int:
    from hermes_cli.harness_parts.persona import chat_delete

    return chat_delete._cmd_persona_chat_delete(args)


def _instance_create_via_cli(args) -> int:
    from hermes_cli.harness_parts.persona import lifecycle_commands

    return lifecycle_commands._cmd_persona_instance_create(args)


def bind_mission_chat_door() -> None:
    bind_mission_chat_turn(_mission_chat_turn_via_cli)
    bind_open_chat(_open_chat_via_cli)
    bind_chat_verb(CHAT_DELETE_VERB, _chat_delete_via_cli)
    bind_chat_verb(INSTANCE_CREATE_VERB, _instance_create_via_cli)
