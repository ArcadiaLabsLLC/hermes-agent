"""RT-CHAT-TURN-MODEL-AND-REDO through the real chat turn.

A send with ``turn_model`` runs THAT turn on the model and writes it nowhere; with ``retry_of``
naming the chat's latest delivered turn it is a redo: admitted, the redone turn's rows are left
out of its model input (and of every later turn's), its record names the origin and the model.
Plan: Eternia ``docs/mission_control/planned/REGENERATE_WITH_ANOTHER_MODEL_2026-11-12.md`` decision 3.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.mission_chat_outcome import ChatErrorKind
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT, _args, _envelopes, _install_chat_lane

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


@pytest.fixture
def lane(monkeypatch):
    """The production handler on ONE shared transcript DB, with a provider spy recording each call."""

    from hermes_cli.harness_parts.persona import chat_turn_message
    from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run
    from tests.agent_runtime.persona_assignments_helpers import _TranscriptDB

    handler = _install_chat_lane(monkeypatch)
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    calls: list[dict] = []

    class _Spy:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            calls.append({"message": message, **kwargs})
            # What the real runtime persists: the turn's rows, keyed by its client_message_id.
            cmid = kwargs["client_message_id"]
            db.append_message(kwargs["session_id"], "user", message, platform_message_id=cmid)
            db.append_message(kwargs["session_id"], "assistant", f"reply {len(calls)}",
                              platform_message_id=f"{cmid}:assistant")
            return SimpleNamespace(final_response=f"reply {len(calls)}", input_tokens=1, output_tokens=2,
                                   total_tokens=3, raw={})

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Spy)
    return SimpleNamespace(handler=handler, db=db, calls=calls)


def _send(lane, capsys, cmid: str, **extra) -> tuple[int, dict]:
    args = _args(cmid)
    for key, value in extra.items():
        setattr(args, key, value)
    code = lane.handler._cmd_mission_chat_message(args)
    frames = _envelopes(capsys)
    return code, ([f for f in frames if f.get("capability_id") == "mission.chat.message"] or frames)[-1]


def _history_ids(call: dict) -> set[str]:
    return {str(row.get("platform_message_id") or "").split(":")[0] for row in call["conversation_history"] or ()}


def _stored_chat_model(lane) -> object:
    from agent_runtime.persona_chat_session import _chat_model_override_from_config, _session_model_config

    return _chat_model_override_from_config(_session_model_config(lane.db, ROOT))


def test_a_redo_of_the_latest_reply_runs_on_its_model_alone_and_leaves_the_redone_turn_out(
    lane, capsys, isolate_agent_runtime_root
):
    """Mutations: drop ``_is_redo_of`` from ``_admit_retry`` -> the redo is refused; drop the
    ``redone_message_ids`` union in ``_build_context`` -> cm-2 is in the redo's model input."""

    for cmid in ("cm-1", "cm-2"):
        assert _send(lane, capsys, cmid)[0] == 0
    assert "cm-1" in _history_ids(lane.calls[-1])
    before = _stored_chat_model(lane)

    code, answer = _send(lane, capsys, "cm-3", retry_of="cm-2", turn_provider="openrouter", turn_model="second-model")

    assert code == 0, answer
    redo = lane.calls[-1]
    assert (redo["provider_override"], redo["model_override"]) == ("openrouter", "second-model")
    assert "cm-1" in _history_ids(redo) and "cm-2" not in _history_ids(redo)
    record = mission_chat_turn_record(session_id=ROOT, client_message_id="cm-3")
    assert record["retry_of"] == "cm-2"
    assert (record["turn_provider"], record["turn_model"]) == ("openrouter", "second-model")
    assert _stored_chat_model(lane) == before  # the chat's own model never moved

    assert _send(lane, capsys, "cm-4")[0] == 0
    after = lane.calls[-1]
    assert after["model_override"] != "second-model"
    assert {"cm-1", "cm-3"} <= _history_ids(after) and "cm-2" not in _history_ids(after)


@pytest.mark.parametrize("extra", [
    {"retry_of": "cm-1", "turn_model": "second-model"},  # an OLDER delivered turn
    {"retry_of": "cm-2"},                                 # the latest, but no model: a plain retry of a delivered turn
])
def test_a_redo_of_anything_but_the_latest_delivered_turn_on_a_named_model_is_refused(
    lane, capsys, isolate_agent_runtime_root, extra
):
    for cmid in ("cm-1", "cm-2"):
        assert _send(lane, capsys, cmid)[0] == 0

    code, answer = _send(lane, capsys, "cm-3", **extra)

    assert code == 2
    assert answer["error_kind"] == ChatErrorKind.CHAT_TURN_RETRY_TARGET_INVALID
    assert len(lane.calls) == 2
    assert mission_chat_turn_record(session_id=ROOT, client_message_id="cm-3") is None


def test_a_turn_model_beside_a_chat_model_change_is_refused(lane, capsys, isolate_agent_runtime_root):
    code, answer = _send(lane, capsys, "cm-1", turn_model="second-model", model="third-model")

    assert code == 2, answer
    assert "turn_provider/turn_model cannot be combined" in str(answer)
    assert lane.calls == []


def test_the_redone_reply_names_its_redo_and_the_redo_reply_names_its_model(isolate_agent_runtime_root):
    """Mutation: drop ``_carry_redo`` from ``_AgentCurator.after_row`` -> neither key is on a reply row."""

    from agent_runtime.mission_chat_turns.journal import persist_mission_chat_turn
    from agent_runtime.operator_channels import _conversation_history_message
    from agent_runtime.persona_chat_history.history_rows import _safe_recent_messages
    from tests.agent_runtime.test_persona_chat_history_curation import FakeSessionDB

    session = "s-redo"
    persist_mission_chat_turn(session_id=session, client_message_id="cm-orig", turn_id="cm-orig", elements=[],
                              state="projected")
    persist_mission_chat_turn(session_id=session, client_message_id="cm-redo", turn_id="cm-redo", elements=[],
                              state="projected", metadata={"retry_of": "cm-orig", "turn_provider": "openrouter",
                                                           "turn_model": "second-model"})
    messages = [{"id": f"{role}-{cmid}", "role": role, "content": text, "platform_message_id": cmid}
                for cmid, role, text in (("cm-orig", "user", "go"), ("cm-orig", "assistant", "first"),
                                         ("cm-redo", "user", "go"), ("cm-redo", "assistant", "second"))]
    rows, status, _unread = _safe_recent_messages(FakeSessionDB(messages), session_id=session)
    assert status == "safe"
    replies = {row["client_message_id"]: row for row in rows if row["role"] == "agent"}
    assert replies["cm-orig"]["retried_as"] == "cm-redo"
    assert (replies["cm-redo"]["turn_provider"], replies["cm-redo"]["turn_model"]) == ("openrouter", "second-model")
    assert "retried_as" not in replies["cm-redo"] and "turn_model" not in replies["cm-orig"]
    projected = _conversation_history_message(replies["cm-redo"], channel_id="chan-1", index=0, persona_id="neko",
                                              persona_instance_id="personainst_neko", display_names={})
    assert projected["turn_model"] == "second-model" and projected["turn_provider"] == "openrouter"
