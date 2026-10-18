"""One ``status_callback``, one calling convention: the fork's dict receipts reach only a ReceiptSink.

Upstream's surfaces install a two-argument ``status_callback(kind, text)``; before the sink, the
fork's timing receipts were handed to it as one dict, and the TUI's ``_agent_status_update``
published the stringified dict as a ``status.update`` kind.
"""

import time
from types import SimpleNamespace

from agent_runtime.conversation_observability import _emit_conversation_timing, _emit_phase_marker
from agent_runtime.init_observability import init_timing_callback
from agent_runtime.receipt_sink import ReceiptSink, receipt_callback


def test_an_upstream_two_argument_callback_never_receives_a_receipt(monkeypatch):
    import tui_gateway.agent_callbacks as tui

    published: list[tuple] = []
    monkeypatch.setattr(tui, "_status_update", lambda *args: published.append(args), raising=False)
    monkeypatch.setattr(tui, "_agent_presentation_enabled", lambda sid, diagnostic=False: True)
    agent = SimpleNamespace(status_callback=lambda kind, text=None: tui._agent_status_update("sid", kind, text))

    _emit_conversation_timing(agent, "turn_context", time.perf_counter())
    _emit_phase_marker(agent, "conversation_preflight_done")
    init_timing_callback(agent.status_callback)("api_mode_setup")

    assert published == []


def test_a_sink_takes_receipts_on_its_own_door_and_upstream_status_on_the_call():
    receipts: list[dict] = []
    statuses: list[tuple] = []
    sink = ReceiptSink(receipts.append, lambda kind, text: statuses.append((kind, text)))
    agent = SimpleNamespace(status_callback=sink)

    _emit_conversation_timing(agent, "turn_context", time.perf_counter())
    sink("lifecycle", "Preflight: loading tools")

    assert [r["step"] for r in receipts] == ["conversation_turn_context"]
    assert statuses == [("lifecycle", "Preflight: loading tools")]
    assert receipt_callback(lambda kind, text=None: None) is None
