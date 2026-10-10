"""CLI contract for a turn whose request never left the process (D2.02).

The empty-Base-console incident: a profile with no provider configured. The
turn crossed the provider boundary (``provider_submitted`` is journaled BEFORE
the provider is resolved), agent construction raised "No LLM provider
configured", and the turn settled ``outcome_unknown`` — a frozen console row
asking the operator to adjudicate a request nobody was ever asked.

The real raise is in ``AIAgent`` construction (``agent/agent_init.py``), which
the profile runner performs BEFORE it calls ``agent_ready_callback``; the fake
below raises the same type at the same point, i.e. without calling it. The
sibling row calls the callback first, which is what a request that DID leave
looks like, and must stay ``outcome_unknown``.

Driven through the real ``_cmd_mission_chat_message``, reading the emitted
envelope and the persisted journal record.
"""

from __future__ import annotations

import json

import pytest

from hermes_cli.harness_parts.persona import chat_turn_message

from agent_runtime.mission_chat_outcome import ChatErrorKind, ExecutionState

from .test_mission_chat_budget_payload import (
    _NEGATIONS,
    _RESOLVE_INSTRUCTIONS,
    _RESOLVE_VERBS,
    _SESSION_ID,
    _args,
    _seed,
    isolate_agent_runtime_root,  # noqa: F401 — fixture re-export
)

NO_PROVIDER = "No LLM provider configured. Run `hermes model` to select a provider."


def _unconfigured_provider(*, request_started: bool):
    from agent.auxiliary_unavailable import ProviderNotConfiguredError

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            if request_started:
                kwargs["agent_ready_callback"](object())
            raise ProviderNotConfiguredError(NO_PROVIDER)

    return _Provider


@pytest.fixture
def unavailable_envelope(monkeypatch, capsys, isolate_agent_runtime_root):
    _seed(monkeypatch, _unconfigured_provider(request_started=False))
    code = chat_turn_message._cmd_mission_chat_message(_args("no_provider_turn"))
    return code, json.loads(capsys.readouterr().out)


def test_a_turn_with_no_provider_settles_the_typed_unavailable_pair(unavailable_envelope):
    code, payload = unavailable_envelope
    assert code == 2
    assert payload["execution_state"] == ExecutionState.FAILED
    assert payload["error_kind"] == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    # The incident's rendering, named so a regression to it is unmistakable.
    assert payload["error_kind"] != ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN
    assert payload["turn_resolution_required"] is False
    assert payload["journal_state"] == "provider_refused"
    block = payload["provider_refusal"]
    assert block["status_code"] == 0
    assert block["reason"] == "provider_unavailable"
    assert "No LLM provider configured" in block["message"]
    assert "configure a provider" in payload["next_expected"]


def test_the_record_is_terminal_and_carries_the_harness_block(unavailable_envelope):
    from agent_runtime.mission_chat_turns import (
        INFLIGHT_TURN_STATES,
        OPERATOR_RESOLVABLE_TURN_STATES,
        TERMINAL_TURN_STATES,
        mission_chat_turn_record,
    )

    record = mission_chat_turn_record(
        session_id=_SESSION_ID, client_message_id="no_provider_turn"
    )
    assert record is not None
    assert record["state"] == "provider_refused"
    assert record["state"] in TERMINAL_TURN_STATES
    assert record["state"] not in INFLIGHT_TURN_STATES
    assert record["state"] not in OPERATOR_RESOLVABLE_TURN_STATES
    assert record["provider_refusal"]["status_code"] == 0
    assert record["provider_refusal"]["reason"] == "provider_unavailable"


def test_the_payload_never_routes_the_operator_to_turn_resolve(unavailable_envelope):
    _, payload = unavailable_envelope
    for text in (value for value in payload.values() if isinstance(value, str)):
        lowered = text.lower()
        for phrase in _RESOLVE_INSTRUCTIONS:
            assert phrase not in lowered, f"{phrase!r} in {text!r}"
        if any(verb in lowered for verb in _RESOLVE_VERBS):
            assert any(negation in lowered for negation in _NEGATIONS), text


def test_a_resend_of_the_same_id_reports_the_same_typed_pair(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    _seed(monkeypatch, _unconfigured_provider(request_started=False))
    assert chat_turn_message._cmd_mission_chat_message(_args("no_provider_turn")) == 2
    capsys.readouterr()
    code = chat_turn_message._cmd_mission_chat_message(_args("no_provider_turn"))
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["error_kind"] == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    assert payload["journal_state"] == "provider_refused"
    assert payload["turn_resolution_required"] is False
    assert payload["provider_refusal"]["reason"] == "provider_unavailable"
    assert "configure a provider" in payload["next_expected"]


def test_the_same_error_after_the_request_started_stays_ambiguous(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    """The phase decides, not the exception type: once the request left the
    process its answer can be lost, and that is still ``outcome_unknown``."""

    from agent_runtime.mission_chat_turns import mission_chat_turn_record

    _seed(monkeypatch, _unconfigured_provider(request_started=True))
    code = chat_turn_message._cmd_mission_chat_message(_args("started_turn"))
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["execution_state"] == ExecutionState.BLOCKED
    assert payload["error_kind"] == ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN
    assert "provider_refusal" not in payload
    record = mission_chat_turn_record(
        session_id=_SESSION_ID, client_message_id="started_turn"
    )
    assert record["state"] == "outcome_unknown"
