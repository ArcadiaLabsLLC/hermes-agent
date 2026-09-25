"""Auxiliary room turns enter the real handler without replacing operator state."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime.auxiliary_chat import auxiliary_chat, is_auxiliary_chat
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from tests.agent_runtime.test_persona_assignments import (
    _assignment_config, _TranscriptDB, _mission_chat_test_args, _persona,
)
from hermes_cli.harness_parts.persona import chat_target, chat_turn_message
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run, settle as commit_settle

pytestmark = [pytest.mark.usefixtures("persisted_persona_samples"), pytest.mark.timeout(90)]
ROOM = "persona_chat_personainst_dev_a01234567890"


@pytest.mark.parametrize("outcome", ["success", "failure", "clarify"])
@pytest.mark.parametrize("operator_changes_thread", [False, True])
def test_native_room_turn_preserves_operator_pointer_and_concurrent_row_fields(
    monkeypatch, capsys, isolate_agent_runtime_root, outcome, operator_changes_thread,
):
    db = _TranscriptDB()
    db.create_session(ROOM, "persona_chat", model_config=json.dumps({
        "persona_id": "dev", "persona_instance_id": "personainst_dev",
    }))
    store = PersonaInstanceStore()
    instance = store.ensure_for_persona(_persona("dev"))
    instance.default_chat_session_id = "persona_chat_personainst_dev_b01234567890"
    instance.mode = "chat"
    store.update(instance)
    before = store.get(instance.id)
    calls = []

    class Provider:
        def __init__(self, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            calls.append(message)
            # Positive evidence that the admission phase did not redirect the pointer.
            assert store.get(instance.id).default_chat_session_id == before.default_chat_session_id
            if operator_changes_thread:
                newer = store.get(instance.id)
                newer.default_chat_session_id = "persona_chat_personainst_dev_c01234567890"
                newer.display_name = "New operator label"
                store.update(newer)
            if outcome == "failure":
                raise RuntimeError("deliberate provider failure")
            raw = {"clarify_request": {"question": "Pick a branch", "choices": ["A", "B"]}} if outcome == "clarify" else {}
            return SimpleNamespace(final_response="Pick a branch" if raw else "Room answer", raw=raw,
                input_tokens=1, output_tokens=1, total_tokens=2)

    monkeypatch.setattr(chat_target, "load_agent_runtime_config", _assignment_config)
    monkeypatch.setattr(chat_turn_message, "load_agent_runtime_config", _assignment_config)
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", Provider)
    monkeypatch.setattr(commit_settle, "_maybe_auto_title_persona_chat", lambda **kwargs: None)
    args = _mission_chat_test_args("aux-" + outcome)
    args.session_id = ROOM
    with auxiliary_chat(instance.id, ROOM):
        code = chat_turn_message._cmd_mission_chat_message(args)
    assert calls == [args.message]
    assert not is_auxiliary_chat(instance.id, ROOM)
    after = store.get(instance.id)
    assert after.default_chat_session_id == ("persona_chat_personainst_dev_c01234567890" if operator_changes_thread else before.default_chat_session_id)
    assert after.display_name == ("New operator label" if operator_changes_thread else before.display_name)
    if outcome != "failure":
        assert code == 0
        row = mission_chat_turn_record(session_id=ROOM, client_message_id=args.client_message_id)
        assert row is not None
        result = row["auxiliary_result"]
        assert result["clarify"] == ({"question": "Pick a branch", "choices": ["A", "B"]} if outcome == "clarify" else None)
    else:
        assert code != 0
    capsys.readouterr()


def test_auxiliary_scope_is_exact_and_resets_on_exception():
    with pytest.raises(RuntimeError):
        with auxiliary_chat("personainst_dev", ROOM):
            assert is_auxiliary_chat("personainst_dev", ROOM)
            assert not is_auxiliary_chat("personainst_other", ROOM)
            assert not is_auxiliary_chat("personainst_dev", "persona_chat_personainst_dev_b01234567890")
            raise RuntimeError("exit")
    assert not is_auxiliary_chat("personainst_dev", ROOM)
