"""RT-ANTHROPIC-STREAM-RECEIPT-ABANDONED: the anthropic Messages stream closes
its own receipts.

Before: no anthropic SSE event reached ``observe_stream_event``, so every
``send_window_receipt`` was closed ``end=abandoned first_event_ms=na`` only when
the NEXT request began (87 of 87 on record, 2026-10-25), and a chat's last call
never logged one.

Drives the REAL consume loop (``AIAgent._interruptible_streaming_api_call`` on
``api_mode="anthropic_messages"``) over a scripted SDK stream; the client is
hooked by ``install_transport_phase_trace``, the call the real checkout makes,
which wraps ``messages.stream`` so the loop's events reach the receipt (no seam
in the upstream loop).

Named sabotage (each reds the test): drop the
``observe_anthropic_stream_events`` call in ``install_transport_phase_trace``
(no line at all); drop the anthropic arm of ``stream_gap_receipt._event_role``
(``message_stop`` is no terminal, so no stream-gap line).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_runtime.send_window_receipt import SEND_WINDOW_RECEIPT, SendWindow
from agent_runtime.stream_gap_receipt import STREAM_GAP_RECEIPT
from agent_runtime.transport_phase_trace import install_transport_phase_trace


def _stream_cm(final_message, events):
    stream = MagicMock()
    stream.__iter__ = MagicMock(return_value=iter(events))
    stream.get_final_message = MagicMock(return_value=final_message)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=stream)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def _event(event_type, **fields):
    return SimpleNamespace(type=event_type, **fields)


def _agent():
    from run_agent import AIAgent

    agent = AIAgent(
        api_key="test-key",
        base_url="https://api.anthropic.com",
        model="claude-test",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    agent.api_mode = "anthropic_messages"
    agent._interrupt_requested = False
    agent._anthropic_client = MagicMock()
    agent._anthropic_api_key = "test-key"

    def _request_client(*_args, **_kwargs):
        client = agent._anthropic_client
        install_transport_phase_trace(agent, client)  # what the real checkout calls
        receipt = agent._hermes_stream_gap_receipt
        receipt.probe_factory = None
        receipt.send = SendWindow(probe_factory=None)
        receipt.send.begin(SimpleNamespace(headers={}, content=b"{}"))
        return client

    agent._create_request_anthropic_client = _request_client
    return agent


def _fields(line: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in line.split()[1:] if "=" in part)


def test_an_anthropic_stream_logs_both_receipts_on_its_own_events(caplog):
    agent = _agent()
    final = SimpleNamespace(content=[SimpleNamespace(type="text", text="Hi")], stop_reason="end_turn")
    events = [
        _event("message_start"),
        _event("content_block_start", content_block=SimpleNamespace(type="text", text="")),
        _event("content_block_delta", delta=SimpleNamespace(type="thinking_delta", thinking="hmm")),
        _event("content_block_delta", delta=SimpleNamespace(type="text_delta", text="Hi")),
        _event("message_delta", delta=SimpleNamespace(stop_reason="end_turn"),
               usage=SimpleNamespace(output_tokens=7)),
        _event("message_stop"),
    ]
    agent._anthropic_client.messages.stream.side_effect = [_stream_cm(final, events)]

    with caplog.at_level(logging.INFO):
        response = agent._interruptible_streaming_api_call({"model": "claude-test"})

    assert response is final
    lines = [r.getMessage() for r in caplog.records]
    windows = [line for line in lines if line.startswith(SEND_WINDOW_RECEIPT)]
    gaps = [line for line in lines if line.startswith(STREAM_GAP_RECEIPT)]
    assert len(windows) == 1, lines
    assert len(gaps) == 1, lines
    window, gap = _fields(windows[0]), _fields(gaps[0])
    # Closed by its own first event, not abandoned by the next request.
    assert window["end"] == "event"
    assert window["first_event_ms"] != "na"
    assert gap["end"] == "text"
    assert gap["output_tokens"] == "7"
    assert gap["reasoning_summary_chars"] == "3"
    assert "content_block_delta.thinking_delta:1" in gap["kinds"]
