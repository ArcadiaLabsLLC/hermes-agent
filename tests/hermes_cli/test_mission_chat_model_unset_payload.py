"""A chat turn no tier names a model for never reaches a provider (RT-NO-MODEL-CHAT-SENDS-AND-404S).

The live finding (Eternia w1105i-live-a): a new Base chat whose profile config set only
``providers.anthropic.credential_source`` sent an EMPTY model id to anthropic and settled
``chat_turn_provider_refused`` on its 404. The real ``GPTPersonaRuntime`` now refuses at its own
model resolution (``turn_provider_model``), before the runner, and the turn settles the D2.02
``chat_turn_provider_unavailable`` pair with a ``model_unset`` block and a "choose a model" remedy.

Driven through the real ``_cmd_mission_chat_message`` and the real runtime; only the runner (the
part that would construct an agent and call a provider) is a stand-in that must never run.
"""

from __future__ import annotations

import json

from hermes_cli.harness_parts.persona import chat_turn_message

from agent_runtime.mission_chat_outcome import ChatErrorKind, ExecutionState, classify_turn_failure
from agent_runtime.persona_runtime import GPTPersonaRuntime
from agent_runtime.provider_dependency_error import MODEL_UNSET_REASON, ChatModelUnsetError

from .test_mission_chat_budget_payload import (
    _SESSION_ID,
    _args,
    _seed,
    isolate_agent_runtime_root,  # fixture re-export
)


class _RunnerMustNotRun:
    calls = 0

    def run(self, request, **kwargs):
        type(self).calls += 1
        raise AssertionError("a turn with no model reached the runner")


class _RealRuntime(GPTPersonaRuntime):
    def __init__(self, **kwargs):
        super().__init__(**kwargs, agent_runner=_RunnerMustNotRun())


def _save_dev(model):
    from agent_runtime.personas import AgentPersona
    from agent_runtime.store import AgentStore

    AgentStore().save(AgentPersona(
        id="dev", display_name="dev worker", role="dev", model=model, provider="anthropic",
        api_mode="anthropic_messages", system_prompt_path="agent_runtime/prompts/dev.md",
    ))


def _send(monkeypatch, capsys, model, client_message_id="no_model_turn"):
    _RunnerMustNotRun.calls = 0
    _seed(monkeypatch, _RealRuntime)
    _save_dev(model)
    code = chat_turn_message._cmd_mission_chat_message(_args(client_message_id))
    return code, json.loads(capsys.readouterr().out)


def test_a_turn_with_no_model_settles_unavailable_and_says_choose_a_model(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    code, payload = _send(monkeypatch, capsys, None)

    assert code == 2
    assert _RunnerMustNotRun.calls == 0
    assert payload["execution_state"] == ExecutionState.FAILED
    assert payload["error_kind"] == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    assert payload["turn_resolution_required"] is False
    block = payload["provider_refusal"]
    assert block["status_code"] == 0 and block["reason"] == MODEL_UNSET_REASON
    assert block["provider"] == "anthropic"
    assert "choose a model" in payload["next_expected"]


def test_a_resend_of_the_same_id_replays_the_same_pair(monkeypatch, capsys, isolate_agent_runtime_root):
    _send(monkeypatch, capsys, None)
    code = chat_turn_message._cmd_mission_chat_message(_args("no_model_turn"))
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["error_kind"] == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    assert payload["provider_refusal"]["reason"] == MODEL_UNSET_REASON
    assert "choose a model" in payload["next_expected"]


def test_a_turn_with_a_model_reaches_the_runner(monkeypatch, capsys, isolate_agent_runtime_root):
    _send(monkeypatch, capsys, "claude-test", client_message_id="model_turn")
    assert _RunnerMustNotRun.calls == 1


def test_the_classifier_settles_it_whatever_the_phase_flags_say():
    """Pre-token like a dependency refusal: no phase evidence can make it ambiguous."""

    outcome = classify_turn_failure(ChatModelUnsetError(provider="anthropic"), provider_submitted=True)
    assert outcome.error_kind == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    assert outcome.provider_refusal.reason == MODEL_UNSET_REASON
    assert "choose a model" in outcome.provider_refusal.next_expected()


def test_the_transcript_marker_says_choose_a_model(monkeypatch, capsys, isolate_agent_runtime_root):
    from agent_runtime.persona_chat_history.markers import _terminal_turn_marker_rows

    _send(monkeypatch, capsys, None)
    (marker,) = _terminal_turn_marker_rows(session_id=_SESSION_ID, assistant_client_message_ids=set())
    assert marker["provider_refusal"]["reason"] == MODEL_UNSET_REASON
    assert "no model is chosen" in marker["text"]


def _send_on_one_db(monkeypatch, capsys, model, client_message_id="no_model_turn"):
    from .test_mission_chat_budget_payload import _TranscriptDB

    _RunnerMustNotRun.calls = 0
    _seed(monkeypatch, _RealRuntime)
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    _save_dev(model)
    code = chat_turn_message._cmd_mission_chat_message(_args(client_message_id))
    capsys.readouterr()
    return code, db


def _operator_rows(db, client_message_id="no_model_turn"):
    return [row for rows in db.messages.values() for row in rows
            if row["role"] == "user" and row.get("platform_message_id") == client_message_id]


def test_the_refused_message_is_stored_beside_its_refusal(monkeypatch, capsys, isolate_agent_runtime_root):
    """RT-REFUSED-CHAT-MESSAGE-NOT-STORED (owner RULED 2026-11-09): the message survives a relaunch.

    MUTATION: drop the ``_keep_refused_message()`` call in ``_SettlePhases._settle_failure`` and the
    first assert reddens (no operator row: SessionDB held only the refusal's journal record).
    """

    code, db = _send_on_one_db(monkeypatch, capsys, None)
    assert code == 2 and _RunnerMustNotRun.calls == 0
    (row,) = _operator_rows(db)
    assert row["content"] == "please answer"
    # A resend of the same id replays the refusal and stores nothing twice.
    chat_turn_message._cmd_mission_chat_message(_args("no_model_turn"))
    capsys.readouterr()
    assert len(_operator_rows(db)) == 1


class _RunnerWritesItsRowThenFails:
    db = None

    def run(self, request, **kwargs):
        type(self).db.append_message("persona_chat_personainst_dev", "user", "please answer",
                                     platform_message_id="native_turn")
        raise RuntimeError("the agent never sent a request")


class _NativeRowRuntime(GPTPersonaRuntime):
    def __init__(self, **kwargs):
        super().__init__(**kwargs, agent_runner=_RunnerWritesItsRowThenFails())


def test_a_row_the_runtime_already_wrote_is_not_written_twice(monkeypatch, capsys, isolate_agent_runtime_root):
    """MUTATION: drop the ``.get("operator")`` early return in ``_keep_refused_message`` and this
    reddens (two operator rows for one id)."""

    from .test_mission_chat_budget_payload import _TranscriptDB

    _seed(monkeypatch, _NativeRowRuntime)
    db = _RunnerWritesItsRowThenFails.db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    _save_dev("claude-test")
    code = chat_turn_message._cmd_mission_chat_message(_args("native_turn"))
    payload = json.loads(capsys.readouterr().out)
    assert code == 2 and payload["provider_refusal"]["status_code"] == 0
    assert len(_operator_rows(db, "native_turn")) == 1
