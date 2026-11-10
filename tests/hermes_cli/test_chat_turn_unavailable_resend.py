"""A resend of a turn the harness refused before it left Hermes replays the unavailable pair.

RT-DEPENDENCY-REFUSAL-RESEND-REPLAYS-REFUSED: a turn settled on ``ProviderDependencyError``
(``provider_refusal.reason`` ``runtime_dependency_*``, harness ``status_code`` 0) first answered
``chat_turn_provider_unavailable``, and its resend replayed ``chat_turn_provider_refused`` "refused by the
model provider", because the replay and the history marker keyed the unavailable arm on the reason.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.mission_chat_outcome import ChatErrorKind, refusal_never_left_hermes
from agent_runtime.persona_chat_history.markers import _terminal_turn_marker_rows
from hermes_cli.harness_parts.persona.chat_turn_commit.admit import _provider_refused_payload

DEPENDENCY = {"status_code": 0, "reason": "runtime_dependency_missing", "provider": "anthropic",
              "missing_packages": ["anthropic"], "repair_hint": "pip install anthropic"}


def _replay(block):
    turn = SimpleNamespace(journal={"provider_refusal": block, "turn_id": "t"}, session_id="s", client_message_id="t")
    return _provider_refused_payload(turn)


def test_a_dependency_refusal_resend_replays_the_unavailable_pair():
    data = _replay(DEPENDENCY)
    assert data["error_kind"] == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    assert "refused by the model provider" not in data["error"]
    assert "repair the runtime dependencies" in data["next_expected"]
    assert data["provider_refusal"] == DEPENDENCY


@pytest.mark.parametrize("reason", ["provider_unavailable", "model_unset"])
def test_the_other_harness_refusals_keep_their_unavailable_pair(reason):
    data = _replay({"status_code": 0, "reason": reason})
    assert data["error_kind"] == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    assert ("no model is chosen" in data["error"]) is (reason == "model_unset")


def test_a_provider_http_refusal_still_replays_refused():
    data = _replay({"status_code": 429, "reason": "usage_limit_reached"})
    assert data["error_kind"] == ChatErrorKind.CHAT_TURN_PROVIDER_REFUSED


@pytest.mark.parametrize("block, expected", [
    ({"status_code": 0, "reason": "anything"}, True),
    ({"status_code": False, "reason": "provider_unavailable"}, False),
    ({"status_code": 403}, False), ({}, False), (None, False),
])
def test_never_left_hermes_reads_the_status_code(block, expected):
    assert refusal_never_left_hermes(block) is expected


def test_the_history_marker_says_a_dependency_refusal_never_left_hermes():
    record = {"state": "provider_refused", "client_message_id": "dep", "provider_refusal": DEPENDENCY}
    rows = _terminal_turn_marker_rows(session_id="base", assistant_client_message_ids=set(), records=[record])
    assert len(rows) == 1 and "never left Hermes" in rows[0]["text"]
