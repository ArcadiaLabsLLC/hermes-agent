"""The runtime's door onto the CLI's mission-chat turn (program ruling Q10).

A mission-chat turn has ONE front door, the CLI handler
``hermes_cli.harness_parts.persona.chat_turn_message._cmd_mission_chat_message``
(session dedup, transcript persistence, prompt observability, the relay
guard). Three callers outside the CLI run a turn in-process through it — the
agent-chat tool's inline relay (``tools/agent_chat/send.py``), the dispatch
delivery's forged turn (``agent_runtime/dispatch_delivery/forge.py``, lane B3)
and the native discussion worker (``agent_runtime/discussions/native.py``) —
and none may import the CLI namespace: that is the runtime reaching UP.

The same door carries the CLI's OPEN-CHAT handler
(``chat_open._cmd_persona_instance_open_chat``), which the method lane's
``runtime.persona.open_chat`` shim (``agent_runtime/persona_open_chat.py``)
runs in-process: :func:`bind_open_chat` / :func:`run_open_chat`, the same
payload-sink contract and the same typed refusal when unbound (lane W3-B).

So the CLI registers what the runtime needs. :func:`bind_mission_chat_turn` is
called at plugin registration (``plugins/eternia-harness`` ``register``) and at
serve boot (``ServeSession._boot_and_serve``), both through
``hermes_cli.harness_parts.mission_chat_door_binding``; a caller runs a turn
through :func:`run_mission_chat_turn`. An unbound door raises
:class:`MissionChatDoorUnbound` — a typed refusal, never a silent no-op.

Layer: ``models`` — it imports nothing, so every layer may call it (W0-G6).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__layer__ = "models"
__all__ = [
    "MissionChatDoorUnbound",
    "bind_mission_chat_turn",
    "bind_open_chat",
    "mission_chat_turn_bound",
    "run_mission_chat_turn",
    "run_open_chat",
]

_turn: Callable[[Any], int] | None = None
_open_chat: Callable[[Any], int] | None = None


class MissionChatDoorUnbound(RuntimeError):
    """No mission-chat turn handler is bound in this process."""


def bind_mission_chat_turn(handler: Callable[[Any], int] | None) -> None:
    """Bind the turn handler (``None`` unbinds). The last binding wins."""
    global _turn
    _turn = handler


def bind_open_chat(handler: Callable[[Any], int] | None) -> None:
    """Bind the open-chat handler (``None`` unbinds). The last binding wins."""
    global _open_chat
    _open_chat = handler


def mission_chat_turn_bound() -> bool:
    return _turn is not None


def _run_handler(handler: Callable[[Any], int] | None, what: str, args: Any) -> tuple[int, dict | None]:
    if handler is None:
        raise MissionChatDoorUnbound(
            f"no {what} handler is bound in this process: the harness "
            "plugin binds it at registration and harness serve at boot, and "
            "neither has run here"
        )
    payloads: list[dict] = []
    args.payload_sink = payloads.append
    exit_code = handler(args)
    return exit_code, (payloads[-1] if payloads else None)


def run_mission_chat_turn(args: Any) -> tuple[int, dict | None]:
    """Run one mission-chat turn in-process: ``(exit_code, payload)``.

    The handler hands its payload dict over through ``args.payload_sink`` (never
    stdout — ``redirect_stdout`` rebinds ``sys.stdout`` process-globally); the
    door installs the sink and returns the LAST payload, or ``None`` when the
    handler produced none.
    """
    return _run_handler(_turn, "mission-chat turn", args)


def run_open_chat(args: Any) -> tuple[int, dict | None]:
    """Open a chat in-process through the CLI's open-chat handler.

    Same contract as :func:`run_mission_chat_turn`: ``(exit_code, last payload
    or None)``, :class:`MissionChatDoorUnbound` when nothing is bound.
    """
    return _run_handler(_open_chat, "open-chat", args)
