"""Native provider evidence survives the Harness outcome and journal boundaries."""

from __future__ import annotations

import time

import pytest

from agent_runtime.mission_chat_outcome import (
    AMBIGUOUS_400_FAILURE_REASONS, ChatErrorKind, ExecutionState,
    PROVIDER_REFUSAL_STATUS_CODES, ProviderRefusal, classify_turn_failure, provider_refusal,
)
from agent_runtime.mission_chat_turns import safe_provider_refusal
from agent_runtime.profile_runner import ProfileRunnerError

LIVE_SUMMARY = "HTTP 429: The usage limit has been reached"
LIVE_CONTEXT = {
    "status_code": 429,
    "reason": "usage_limit_reached",
    "message": "The usage limit has been reached",
    "provider": "openai-codex",
    "model": "gpt-5.6-luna",
    "failure_reason": "rate_limit",
}


def test_profile_runner_error_defaults_to_no_verdict():
    """Every other raise site in the runner passes no block, and must not be
    read as "the provider was fine"."""

    assert ProfileRunnerError("profile not ready").provider_error is None


# ---------------------------------------------------------------------------
# 2. the reader
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", sorted(PROVIDER_REFUSAL_STATUS_CODES))
def test_every_declared_refusal_status_reads_as_a_refusal(status):
    exc = ProfileRunnerError("x", provider_error={"status_code": status})
    verdict = provider_refusal(exc)
    assert verdict is not None and verdict.status_code == status


@pytest.mark.parametrize("status", [500, 502, 503, 504, 529])
def test_a_server_error_stays_ambiguous(status):
    """A 5xx is not a verdict. The provider did not decide anything about this
    request and it may well have run — which is exactly what
    ``outcome_unknown`` means and the one case that must keep meaning it."""

    exc = ProfileRunnerError("x", provider_error={"status_code": status})
    assert provider_refusal(exc) is None


def test_a_transport_failure_with_no_block_stays_ambiguous():
    assert provider_refusal(ProfileRunnerError("Connection reset by peer")) is None
    assert provider_refusal(RuntimeError("stream died after first byte")) is None


@pytest.mark.parametrize("reason", sorted(AMBIGUOUS_400_FAILURE_REASONS))
def test_a_repairable_400_is_not_a_refusal(reason):
    exc = ProfileRunnerError("x", provider_error={"status_code": 400, "failure_reason": reason})
    assert provider_refusal(exc) is None


def test_an_unclassified_400_stays_ambiguous():
    """Over-approximating toward ambiguity costs one honest "I cannot prove
    this"; over-approximating the other way tells an operator their plan is out
    of usage when it is not."""

    exc = ProfileRunnerError("x", provider_error={"status_code": 400})
    assert provider_refusal(exc) is None


def test_a_classified_400_that_is_not_repairable_is_a_refusal():
    exc = ProfileRunnerError("x", provider_error={"status_code": 400, "failure_reason": "billing"})
    verdict = provider_refusal(exc)
    assert verdict is not None and verdict.failure_reason == "billing"


def test_a_non_numeric_status_is_not_a_refusal():
    exc = ProfileRunnerError("x", provider_error={"status_code": "not a number"})
    assert provider_refusal(exc) is None


# ---------------------------------------------------------------------------
# the reset, in the three shapes providers actually send
# ---------------------------------------------------------------------------
def test_resets_in_seconds_reads_an_epoch():
    now = 1_789_000_000.0
    refusal = ProviderRefusal(429, reset_at=now + 10_800)
    assert refusal.resets_in_seconds(now=now) == 10_800


def test_resets_in_seconds_reads_a_bare_duration():
    """``x-ratelimit-reset`` is forwarded verbatim and providers send it both
    ways. 10^9 seconds is 31 years as a duration and 2001 as an epoch, so the
    two are separable without guessing."""

    assert ProviderRefusal(429, reset_at=3600).resets_in_seconds(now=1_789_000_000.0) == 3600


def test_resets_in_seconds_reads_an_iso_timestamp():
    now = 1_789_000_000.0
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now + 600))
    assert ProviderRefusal(429, reset_at=stamp).resets_in_seconds(now=now) == 600


@pytest.mark.parametrize(
    "reset_at",
    [None, "", "soon", True, 1_789_000_000.0 - 60],
)
def test_an_unreadable_or_past_reset_is_absence(reset_at):
    """A zero here would render as "it resets in about 0 h" — a sentence
    nobody said."""

    refusal = ProviderRefusal(429, reset_at=reset_at)
    assert refusal.resets_in_seconds(now=1_789_000_000.0) is None
    assert "resets_in_seconds" not in refusal.as_dict(now=1_789_000_000.0)


def test_the_reset_positive_control_projects_differently():
    """POSITIVE CONTROL for the block: the same refusal, one field changed, and
    the projection MUST differ — both in the wire block and in the sentence."""

    now = 1_789_000_000.0
    without = ProviderRefusal(429, reason="usage_limit_reached")
    with_reset = ProviderRefusal(429, reason="usage_limit_reached", reset_at=now + 10_800)

    assert "resets_in_seconds" not in without.as_dict(now=now)
    assert with_reset.as_dict(now=now)["resets_in_seconds"] == 10_800
    assert "resets in" not in without.next_expected(now=now)
    assert "resets in about 3 h" in with_reset.next_expected(now=now)


def test_absent_stays_absent_in_the_wire_block():
    assert ProviderRefusal(401).as_dict() == {"status_code": 401}


# ---------------------------------------------------------------------------
# 3. the seam: runner -> classifier -> journal-safe metadata
# ---------------------------------------------------------------------------
def test_the_live_429_settles_terminal_instead_of_outcome_unknown():
    """The incident, end to end through the two seams it crossed.

    Built the way ``ProfileAgentRunner._run`` builds it (summary + native result evidence), classified the way ``_mission_chat_commit_turn`` classifies
    it. Before this lane the same object produced ``blocked`` /
    ``chat_turn_outcome_unknown``, which the launcher renders as the
    abandon-and-resend banner.
    """

    now = time.time()
    exc = ProfileRunnerError("Reworded failure", provider_error=dict(LIVE_CONTEXT, reset_at=now + 10_800))

    outcome = classify_turn_failure(exc, provider_submitted=True)

    assert outcome.execution_state is ExecutionState.FAILED
    assert outcome.error_kind is ChatErrorKind.CHAT_TURN_PROVIDER_REFUSED
    assert outcome.error_kind != ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN
    verdict = outcome.provider_refusal
    assert verdict is not None
    assert verdict.reason == "usage_limit_reached"
    assert verdict.provider == "openai-codex"
    assert verdict.model == "gpt-5.6-luna"
    assert verdict.resets_in_seconds(now=now) == 10_800
    assert "NO turn-resolve" in outcome.provider_refusal.next_expected(now=now)


def test_the_refused_turn_record_carries_the_block_through_the_real_write_path():
    """The block has to REACH the record, not merely be sanitizable.

    Recorded because this test exists only because its mutation survived
    without it: deleting the three lines that wire ``safe_provider_refusal``
    into ``_safe_journal_metadata`` left the whole file green — the sanitizer
    was pinned and the PATH through it was not, which is the "a capture is a
    vehicle" shape. So this walks a record to ``provider_refused`` through
    ``transition_mission_chat_turn`` and reads it back off the store.
    """

    from agent_runtime.mission_chat_turns import (
        MissionChatTurnPersistOutcome,
        TURN_STATE_EXECUTING,
        TURN_STATE_PENDING,
        TURN_STATE_PROVIDER_REFUSED,
        mission_chat_turn_record,
        transition_mission_chat_turn,
    )

    now = time.time()
    block = ProviderRefusal(
        429,
        reason="usage_limit_reached",
        message="The usage limit has been reached",
        reset_at=now + 10_800,
        provider="openai-codex",
        model="gpt-5.6-luna",
    ).as_dict(now=now)

    for state in (TURN_STATE_PENDING, TURN_STATE_EXECUTING):
        transition_mission_chat_turn(
            session_id="s_refused",
            client_message_id="m",
            turn_id="m",
            state=state,
            metadata={"provider_submitted": state == TURN_STATE_EXECUTING},
        )
    outcome = transition_mission_chat_turn(
        session_id="s_refused",
        client_message_id="m",
        turn_id="m",
        state=TURN_STATE_PROVIDER_REFUSED,
        metadata={"provider_submitted": True, "provider_refusal": block},
    )

    assert outcome is MissionChatTurnPersistOutcome.PERSISTED
    record = mission_chat_turn_record(session_id="s_refused", client_message_id="m")
    assert record["state"] == TURN_STATE_PROVIDER_REFUSED
    stored = record["provider_refusal"]
    assert stored["status_code"] == 429
    assert stored["reason"] == "usage_limit_reached"
    assert stored["resets_in_seconds"] == block["resets_in_seconds"]
    assert stored["provider"] == "openai-codex"
    assert stored["model"] == "gpt-5.6-luna"


def test_the_journal_admits_the_whole_block_and_nothing_else():
    """The turn record's metadata is a strict whitelist, so a block that is
    merely PASSED is a block that is silently dropped. Every key the frame
    promises must survive the sanitizer — and the provider's own text, which is
    attacker-influenced on the far side of an HTTP boundary, must be bounded."""

    now = time.time()
    block = ProviderRefusal(
        429,
        reason="usage_limit_reached",
        message="The usage limit has been reached",
        reset_at=now + 10_800,
        provider="openai-codex",
        model="gpt-5.6-luna",
        failure_reason="rate_limit",
    ).as_dict(now=now)
    stored = safe_provider_refusal(dict(block, injected="dropped"))
    assert set(stored) == set(block)
    assert stored["status_code"] == 429
    assert stored["reason"] == "usage_limit_reached"
    assert stored["resets_in_seconds"] == block["resets_in_seconds"]
    assert "injected" not in stored

    huge = safe_provider_refusal({"status_code": 429, "message": "x" * 5000})
    assert len(huge["message"]) < 5000
    assert safe_provider_refusal({"reason": "usage_limit_reached"}) is None
    assert safe_provider_refusal("429") is None
