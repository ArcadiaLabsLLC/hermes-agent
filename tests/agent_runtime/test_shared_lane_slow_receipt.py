"""A deferred reply that waited on the shared lane says so (lane w1123k-chatissues).

Live 2026-11-23 (owner box): Eternia's ``runtime.operator.conversation.list`` and
``history.pending`` reads came back ``rpc_timeout`` and the serve's agent.log held no
line for either, so nothing said whether they waited for a worker or ran slow.
"""

from __future__ import annotations

import logging
import threading

from agent_runtime.serve_rpc.protocol import deferred_reply
from hermes_cli.harness_parts.serve.request_pool import SHARED_LANE_SLOW_MS, RequestPool


def _fields(message: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in message.split() if "=" in token)


def test_a_reply_queued_behind_busy_workers_names_its_wait(caplog):
    pool = RequestPool(1)
    release = threading.Event()
    try:
        with caplog.at_level(logging.INFO, logger="hermes_cli.harness_parts.serve.request_pool"):
            holder = pool.submit(release.wait, 30, label="argv:holder")
            build = deferred_reply("req-1", "runtime.operator.conversation.list", lambda: {"ok": True})
            reply = pool.submit(build, label=build.method_name)
            threading.Timer(SHARED_LANE_SLOW_MS / 1000 + 0.2, release.set).start()
            assert reply.result(timeout=30) == {"ok": True}
            holder.result(timeout=30)
    finally:
        release.set()
        pool.shutdown()
    lines = [_fields(r.getMessage()) for r in caplog.records if r.getMessage().startswith("shared_lane_slow")]
    waited = [line for line in lines if line["label"] == "runtime.operator.conversation.list"]
    assert waited, lines
    assert int(waited[0]["queue_ms"]) >= SHARED_LANE_SLOW_MS
    assert waited[0]["busy_at_submit"] == "1"


def test_a_quick_reply_logs_nothing(caplog):
    pool = RequestPool(2)
    try:
        with caplog.at_level(logging.INFO, logger="hermes_cli.harness_parts.serve.request_pool"):
            assert pool.submit(lambda: 7, label="x").result(timeout=10) == 7
    finally:
        pool.shutdown()
    assert not [r for r in caplog.records if r.getMessage().startswith("shared_lane_slow")]


class _Sink:
    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.arrived = threading.Event()

    def emit(self, frame: dict) -> None:
        self.frames.append(frame)
        self.arrived.set()


def _answer_with_the_shared_lane_hung(call):
    """``call(context)`` with both shared workers parked; the frame it answered, or None after 5 s."""

    from functools import partial

    from agent_runtime.serve_rpc.protocol import DEFERRED, RpcContext
    from hermes_cli.harness_parts.serve.lanes import ArgvLanes

    pool = RequestPool(2)
    hung = threading.Event()
    lanes = type("Lanes", (), {"pool": pool, "drain_state": None})()
    sink = _Sink()
    try:
        for _ in range(2):
            pool.submit(hung.wait, 30, label="argv:persona.instance.open-chat")
        answer = call(RpcContext(spawn_reply=partial(ArgvLanes._spawn_reply, lanes, sink)))
        assert answer is DEFERRED
        return sink.frames[0] if sink.arrived.wait(5) else None
    finally:
        hung.set()
        pool.shutdown()


def test_a_hung_shared_lane_never_starves_the_chat_list(monkeypatch):
    """Every shared worker parked (argv work waiting on a chat whose turns never end): the chat
    list, a deferred read, still answers at once, on the read lane."""

    from agent_runtime.serve_rpc import instance_history as list_rpc

    monkeypatch.setattr(list_rpc, "list_instance_conversations",
                        lambda params: {"conversations": [], "next_cursor": None, "legacy_route_id": None})
    frame = _answer_with_the_shared_lane_hung(lambda context: list_rpc.list_conversations(
        "req-list", {"install_id": "install-1", "client_scope": "a" * 64}, context))
    assert frame is not None, "the chat list waited behind the hung shared lane"
    assert frame["id"] == "req-list" and "result" in frame, frame


def test_a_hung_shared_lane_never_starves_history_recovery(monkeypatch):
    """The console's recovery read (``history.pending``, Eternia's "Recovery information could not be
    loaded" when it times out) answers with the shared lane hung too."""

    from agent_runtime.serve_rpc import operator_history

    monkeypatch.setattr(operator_history, "operator_history_pending", lambda params: {"pending": None})
    frame = _answer_with_the_shared_lane_hung(
        lambda context: operator_history.history_pending("req-pending", {}, context))
    # MUTATION: drop ``read_lane=True`` from history_pending and this reddens (None: it waited).
    assert frame is not None and frame["id"] == "req-pending", frame
    assert frame["result"] == {"pending": None}, frame
