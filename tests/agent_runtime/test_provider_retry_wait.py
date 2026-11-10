"""A chat turn sitting out a provider retry tells the console, typed (``provider.retry_wait``).

Runtime row RT-CHAT-PROVIDER-RETRY-WAIT-FRAME (launcher MC-CONSOLE-PROVIDER-429-BACKOFF-SHOWS-THINKING):
an Anthropic 429 waited 600 s while the Agent Console read "Thinking", because the wait was spoken
only on ``thinking_callback``, which the profile runner never wires. These drive the REAL chain —
``settle_unrecovered_error`` → the agent's ``ReceiptSink`` (``StatusEmitter``) → ``ChatProgressSink``
→ ``_ChatProtocolV2Emitter`` — and pin the frame the Launcher reads.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.error_classifier import classify_api_error
from agent.turn_api_error import settle_unrecovered_error
from agent.turn_retry_state import TurnRetryState
from agent_runtime.events import EventLog
from agent_runtime.profile_runner.status import StatusEmitter
from agent_runtime.progress import ChatProgressSink
from agent_runtime.provider_retry_wait import (
    PROVIDER_RETRY_WAIT_PHASE,
    emit_provider_retry_wait,
    safe_provider_retry_wait,
)
from hermes_cli.harness_parts.persona import chat_events


class _Err(Exception):
    def __init__(self, status_code, body, headers=None):
        super().__init__(f"Error code: {status_code} - {body}")
        self.status_code = status_code
        self.message = str(self)
        self.body = body
        self.response = SimpleNamespace(headers=headers or {})


def _anthropic_429(retry_after: int) -> _Err:
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "This request would exceed your account's rate limit."}}
    return _Err(429, body, {"retry-after": str(retry_after)})


class _Agent:
    """The seams ``settle_unrecovered_error``'s backoff branch reads; the rest are no-ops."""

    log_prefix = ""
    verbose = False
    provider = "anthropic"
    model = "claude-opus-4-1"
    base_url = "https://api.anthropic.com"
    platform = "agent_runtime"
    _credential_pool = None
    _current_streamed_assistant_text = ""
    _interrupt_requested = False
    _auto_recovery_cycles = 5

    def __init__(self, status_callback=None):
        self.status_callback = status_callback
        self.thinking_callback = None
        self.waits: list[str] = []

    def _emit_diagnostic_wait(self, text):
        self.waits.append(str(text))

    def _client_log_context(self):
        return ""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def frames(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(chat_events, "_emit_chat_frame", captured.append)
    return captured


@pytest.fixture
def stream(frames):
    """(agent, emitter, event log) wired exactly as the mission-chat handler wires a turn."""
    emitter = chat_events._ChatProtocolV2Emitter(turn_id="turn_1", client_message_id="client_1", emit_frames=True)
    log = EventLog()
    sink = ChatProgressSink(session_id="chat_1", persona_id="dev", event_log=log, on_trace=emitter.progress)
    status = StatusEmitter(SimpleNamespace(progress_callback=sink.callback()), {})
    yield _Agent(status.sink()), emitter, log
    emitter.finish(state="completed")


def _settle_backoff(agent, err, *, retry_count=1, max_retries=3, is_rate_limited=True):
    classified = classify_api_error(err, provider=agent.provider, model=agent.model, base_url=agent.base_url)
    from agent.agent_runtime_helpers import extract_api_error_context

    with patch("agent.turn_api_error.interruptible_backoff_sleep", lambda *a, **k: None, create=True), \
            patch("agent.turn_recovery.interruptible_backoff_sleep", lambda *a, **k: None):
        return settle_unrecovered_error(
            agent, api_error=err, classified=classified, _retry=TurnRetryState(primary_recovery_attempted=True),
            status_code=err.status_code, error_msg=str(err).lower(), is_context_length_error=False,
            is_rate_limited=is_rate_limited, _is_zai_coding_overload=False, _provider=agent.provider,
            _base=agent.base_url, _model=agent.model, messages=[], api_messages=[], api_kwargs=None,
            active_system_prompt=None, conversation_history=None, approx_tokens=0, retry_count=retry_count,
            max_retries=max_retries, compression_attempts=0, api_call_count=1,
            error_context=extract_api_error_context(err),
        )


def _of_type(frames, kind):
    return [frame for frame in frames if frame.get("type") == kind]


def test_a_429_wait_reaches_the_stream_as_a_typed_retry_wait_frame(stream, frames):
    agent, emitter, log = stream
    verdict = _settle_backoff(agent, _anthropic_429(120))

    assert verdict.action == "fallthrough"  # the retry runs after the wait
    [frame] = _of_type(frames, "provider.retry_wait")
    assert {k: frame[k] for k in ("protocol_version", "turn_id", "retry_in_seconds", "attempt", "max_attempts")} == {
        "protocol_version": 2, "turn_id": "turn_1", "retry_in_seconds": 120, "attempt": 1, "max_attempts": 3,
    }
    refusal = frame["provider_refusal"]
    assert refusal["status_code"] == 429
    assert refusal["reason"] == "rate_limit_error"
    assert (refusal["provider"], refusal["model"]) == ("anthropic", "claude-opus-4-1")
    assert 100 <= refusal["resets_in_seconds"] <= 120
    assert log.for_session("chat_1") == [], "a wait is a live edge, not a Trace-lane row"
    assert emitter.elements == []


def test_a_5xx_wait_says_when_the_retry_runs_and_claims_no_refusal(stream, frames):
    agent, _, _ = stream
    _settle_backoff(agent, _Err(503, {"error": {"message": "upstream down"}}, {"retry-after": "30"}), is_rate_limited=False)

    [frame] = _of_type(frames, "provider.retry_wait")
    assert frame["retry_in_seconds"] == 30 and frame["attempt"] == 1
    assert "provider_refusal" not in frame


def test_an_agent_without_the_receipt_door_gets_nothing_new():
    """CLI, gateway, TUI and api_server callbacks never receive a dict receipt."""
    seen = []
    agent = _Agent(status_callback=lambda *a: seen.append(a))
    _settle_backoff(agent, _anthropic_429(120))
    assert seen == []
    assert agent.waits, "the upstream live wait line is unchanged"


def test_the_sanitizer_admits_only_its_closed_set():
    raw = {
        "type": "run.progress", "phase": PROVIDER_RETRY_WAIT_PHASE, "retry_in_seconds": 599.6, "attempt": "2",
        "max_attempts": 3, "secret": "sk-ant-xyz",
        "provider_refusal": {"status_code": "429", "reason": "rate_limit_error", "headers": {"x": "y"}},
    }
    assert safe_provider_retry_wait(raw) == {
        "type": "run.progress", "phase": PROVIDER_RETRY_WAIT_PHASE, "retry_in_seconds": 600, "attempt": 2,
        "max_attempts": 3, "provider_refusal": {"status_code": 429, "reason": "rate_limit_error"},
    }
    assert safe_provider_retry_wait({**raw, "attempt": None}) is None
    assert safe_provider_retry_wait({**raw, "phase": "compaction"}) is None


def test_a_failing_receipt_door_never_fails_the_turn():
    def boom(_payload):
        raise RuntimeError("sink down")

    from agent_runtime.receipt_sink import ReceiptSink

    agent = SimpleNamespace(status_callback=ReceiptSink(boom))
    emit_provider_retry_wait(agent, None, {}, wait_seconds=5, attempt=1, max_attempts=3)


# ── RT-RETRY-AFTER-CAP-RETRIES-WEEK-LIMIT: a reset no capped retry can reach ends the cycle ──

_WEEK_LIMIT_S = 3 * 86400 + 6 * 3600  # the live "resets in 3d 6h"


class _FallbackAgent(_Agent):
    def __init__(self, status_callback=None, *, fallback_left=False):
        super().__init__(status_callback)
        self._fallback_left = fallback_left
        self.activated: list[dict] = []

    def _has_pending_fallback(self):
        return self._fallback_left

    def _try_activate_fallback(self, **kwargs):
        self.activated.append(kwargs)
        return self._fallback_left

    def _try_recover_primary_transport(self, *a, **k):
        return False


def _settle_exhaustible(agent, err, *, retry_count=1):
    exhausted = {"failed": True, "failure_reason": "rate_limit", "error": "rate limited"}
    with patch("agent.conversation_loop._arm_fallback_restart", lambda a, m, s, r: s), \
            patch("agent.turn_api_error.max_retries_exhausted_result", lambda *a, **k: dict(exhausted)):
        return _settle_backoff(agent, err, retry_count=retry_count)


def test_a_week_limit_429_ends_the_cycle_with_a_typed_refusal_naming_the_reset(stream, frames):
    from agent_runtime.mission_chat_outcome import provider_refusal_from_block

    agent, _, _ = stream
    agent.__class__ = _FallbackAgent
    agent._fallback_left, agent.activated = False, []
    verdict = _settle_exhaustible(agent, _anthropic_429(_WEEK_LIMIT_S))

    assert verdict.action == "return", "no 600 s sleep into a wall days away"
    assert _of_type(frames, "provider.retry_wait") == []
    # handle_api_error's own _verdict stamps the terminal result on the way out; do the same here.
    from agent.agent_runtime_helpers import extract_api_error_context
    from agent.provider_failure import attach_provider_failure

    err = _anthropic_429(_WEEK_LIMIT_S)
    classified = classify_api_error(err, provider=agent.provider, model=agent.model, base_url=agent.base_url)
    attach_provider_failure(verdict.result, classified, extract_api_error_context(err))
    refusal = provider_refusal_from_block(verdict.result["provider_error"])
    assert refusal is not None and refusal.status_code == 429 and refusal.reason == "rate_limit_error"
    assert _WEEK_LIMIT_S - 60 <= refusal.resets_in_seconds() <= _WEEK_LIMIT_S


def test_a_reset_named_only_by_reset_at_counts_too():
    import time
    from datetime import UTC, datetime

    agent = _FallbackAgent()
    reset = datetime.fromtimestamp(time.time() + _WEEK_LIMIT_S, tz=UTC).isoformat()
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "week limit"}}
    verdict = _settle_exhaustible(agent, _Err(429, body, {"anthropic-ratelimit-tokens-reset": reset}))
    assert verdict.action == "return"


def test_fallback_runs_first_and_carries_the_reset():
    agent = _FallbackAgent(fallback_left=True)
    verdict = _settle_exhaustible(agent, _anthropic_429(_WEEK_LIMIT_S))
    assert verdict.action == "break"
    [call] = agent.activated
    assert call["reset_at"] is not None


@pytest.mark.parametrize(
    "retry_after,retry_count,ends",
    [
        (900, 1, False),  # two capped waits (1200 s) reach a 15 min reset: wait it out
        (1300, 1, True),  # they do not reach 1300 s
        (900, 2, True),  # one wait left (600 s) cannot reach 900 s
        (60, 2, False),  # an ordinary per-minute throttle
    ],
)
def test_only_a_reset_beyond_the_remaining_capped_waits_ends_the_cycle(retry_after, retry_count, ends):
    from agent_runtime.provider_retry_wait import reset_outlasts_retries

    err = _anthropic_429(retry_after)
    from agent.agent_runtime_helpers import extract_api_error_context

    assert reset_outlasts_retries(err, extract_api_error_context(err), retry_count=retry_count, max_retries=3) is ends


def test_a_millisecond_epoch_reset_is_not_read_as_millennia():
    import time

    from agent_runtime.mission_chat_outcome import ProviderRefusal

    in_two_minutes_ms = int((time.time() + 120) * 1000)
    assert 100 <= ProviderRefusal(status_code=429, reset_at=in_two_minutes_ms).resets_in_seconds() <= 120
