"""The runtime's three remaining reaches UP into the CLI take the door (lane W3-B).

``discussions/native.py`` (a turn), ``persona_open_chat.py`` (open-chat) run
their CLI handler through ``agent_runtime.mission_chat_door``; ``peer_directory``
resolves a target through ``agent_runtime.mission_chat_persona``, the resolver
moved down out of ``chat_target``. Each door caller is driven UNBOUND (the typed
refusal, not an import) and BOUND (the positive control: the same call, the
handler set, and the payload arrives).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import mission_chat_door
from agent_runtime.discussions import native
from agent_runtime.mission_chat_door import MissionChatDoorUnbound
from agent_runtime.persona_open_chat import perform_persona_instance_open_chat

ROOT = Path(__file__).resolve().parents[2]
CALLERS = (
    "agent_runtime/discussions/native.py",
    "agent_runtime/peer_directory.py",
    "agent_runtime/persona_open_chat.py",
    "agent_runtime/mission_chat_persona.py",
)


@pytest.mark.parametrize("path", CALLERS)
def test_the_caller_never_imports_the_cli_namespace(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    reaches = [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("hermes_cli"))
        or (isinstance(node, ast.Import) and any(a.name.startswith("hermes_cli") for a in node.names))
    ]
    assert reaches == [], f"{path} imports hermes_cli at line(s) {reaches}"


def test_native_turn_unbound_is_the_typed_refusal(monkeypatch):
    monkeypatch.setattr(mission_chat_door, "_turn", None)
    with pytest.raises(MissionChatDoorUnbound):
        native._invoke_native(SimpleNamespace(payload_sink=lambda _row: None))


def test_native_turn_bound_hands_the_last_payload_to_the_worker(monkeypatch):
    def handler(args):
        args.payload_sink({"stage": "admitted"})
        args.payload_sink({"ok": True})
        return 0

    monkeypatch.setattr(mission_chat_door, "_turn", handler)
    seen: list[dict] = []
    assert native._invoke_native(SimpleNamespace(payload_sink=seen.append)) == 0
    assert seen == [{"ok": True}]


def test_open_chat_unbound_is_a_typed_refusal_on_the_wire(monkeypatch):
    monkeypatch.setattr(mission_chat_door, "_open_chat", None)
    outcome = perform_persona_instance_open_chat({"persona_id": "dev"})
    assert outcome.refusal is not None
    assert outcome.refusal.data["reason"] == "mission_chat_door_unbound"


def test_open_chat_bound_answers_with_the_handler_row(monkeypatch):
    seen = []

    def handler(args):
        seen.append(args.persona_id)
        args.payload_sink({"ok": True, "session_id": "persona_chat_x"})
        return 0

    monkeypatch.setattr(mission_chat_door, "_open_chat", handler)
    outcome = perform_persona_instance_open_chat({"persona_id": "dev"})
    assert outcome.refusal is None
    assert outcome.result["session_id"] == "persona_chat_x"
    assert seen == ["dev"]


def test_the_cli_resolves_a_target_through_the_runtime_resolver():
    from agent_runtime.mission_chat_persona import resolve_mission_chat_persona_id
    from hermes_cli.harness_parts.persona import chat_target

    assert chat_target._resolve_mission_chat_persona_id is resolve_mission_chat_persona_id
