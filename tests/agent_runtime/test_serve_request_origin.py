"""RT-FU-EVERY-REQUEST-SAYS-WHO-IN-ETERNIA-ASKED-AND-HOW-LONG-IT-WAITED: a request's ``origin``
(ids only, on the JSON-RPC envelope) reaches the worker lane's receipts, and every shared- and
read-lane job is counted in a per-minute ``lane_rollup`` line.

Killing mutations, each red recorded in the landing commit: ``deferred_reply`` stamping
``NO_ORIGIN``; ``request_origin._part`` without its substitution; the pool's ``rollup.record``
dropped.
"""

from __future__ import annotations

import logging
import threading
import time

from agent_runtime.serve_rpc.protocol import RpcContext, deferred_reply
from agent_runtime.serve_rpc.request_origin import NO_ORIGIN, PART_LIMIT, current_origin, origin_scope, origin_token
from hermes_cli.harness_parts.serve.request_pool import SHARED_LANE_SLOW_MS, LaneRollup, RequestPool
from tests.agent_runtime.test_shared_lane_slow_receipt import _fields, _Sink

POOL_LOGGER = "hermes_cli.harness_parts.serve.request_pool"
ORIGIN = {"action": "act-7f3a", "caller": "conversationInbox", "trigger": "user:open-home"}


def test_an_origin_is_reduced_to_one_bounded_token():
    assert origin_token({"origin": ORIGIN}) == "act-7f3a/conversationInbox/user:open-home"
    assert origin_token({"origin": {"caller": "a b/c=d", "trigger": "x" * 200}}) == f"-/a_b_c_d/{'x' * PART_LIMIT}"
    for absent in ({}, {"origin": None}, {"origin": "free text"}, {"origin": {"action": True}}, None):
        assert origin_token(absent) == NO_ORIGIN


def test_the_dispatcher_hands_the_origin_to_the_handler_and_an_older_client_is_unchanged(monkeypatch):
    from agent_runtime import serve_rpc
    from agent_runtime.call_authorization import LOCAL_CONSOLE
    from agent_runtime.serve_rpc import registry

    seen: list[str] = []
    monkeypatch.setitem(registry._METHODS, "runtime.test.origin", lambda rid, params, context: (
        seen.append(current_origin()) or {"jsonrpc": "2.0", "id": rid, "result": dict(params)}))
    monkeypatch.setattr(registry, "method_tier", lambda name: "read")
    request = {"jsonrpc": "2.0", "id": "o1", "method": "runtime.test.origin", "params": {"a": 1}}

    with_origin = serve_rpc.handle_request({**request, "origin": ORIGIN}, RpcContext(caller=LOCAL_CONSOLE))
    without = serve_rpc.handle_request(request, RpcContext(caller=LOCAL_CONSOLE))

    assert with_origin["result"] == without["result"] == {"a": 1}  # never in params
    assert seen == ["act-7f3a/conversationInbox/user:open-home", NO_ORIGIN]
    assert current_origin() == NO_ORIGIN


def test_a_deferred_reply_names_its_origin_on_its_slow_line(caplog):
    from hermes_cli.harness_parts.serve.lanes import ArgvLanes

    pool = RequestPool(1)
    release = threading.Event()
    lanes = type("Lanes", (), {"pool": pool, "drain_state": None})()
    sink = _Sink()
    try:
        with caplog.at_level(logging.INFO, logger=POOL_LOGGER):
            pool.submit(release.wait, 30, label="argv:holder")
            with origin_scope(origin_token({"origin": ORIGIN})):
                build = deferred_reply("req-1", "runtime.operator.conversation.read", lambda: {"ok": True})
            assert ArgvLanes._spawn_reply(lanes, sink, build)
            threading.Timer(SHARED_LANE_SLOW_MS / 1000 + 0.2, release.set).start()
            assert sink.arrived.wait(30)
    finally:
        release.set()
        pool.shutdown()
    slow = [_fields(r.getMessage()) for r in caplog.records if r.getMessage().startswith("shared_lane_slow")]
    read = [line for line in slow if line["label"] == "runtime.operator.conversation.read"]
    assert read and read[0]["origin"] == "act-7f3a/conversationInbox/user:open-home", slow
    assert [line["origin"] for line in slow if line["label"] == "argv:holder"] in ([], [NO_ORIGIN])


def test_the_rollup_counts_every_request(caplog):
    pool = RequestPool(2)
    pool.rollup = LaneRollup(window_s=0.3)
    try:
        with caplog.at_level(logging.INFO, logger=POOL_LOGGER):
            for index in range(5):
                pool.submit(lambda: None, label="runtime.a", origin="act-1/x/frame").result(timeout=10)
            pool.submit_read(lambda: None, label="runtime.b").result(timeout=10)
            time.sleep(0.35)
            pool.submit(lambda: None, label="runtime.c", origin="act-2/y/user:send").result(timeout=10)
    finally:
        pool.shutdown()
    lines = [_fields(r.getMessage()) for r in caplog.records if r.getMessage().startswith("lane_rollup")]
    shared = [line for line in lines if line["lane"] == "shared"]
    assert len(shared) == 1, lines  # one line for the closed window; the read lane's is still open
    assert shared[0]["requests"] == "6"
    assert shared[0]["methods"] == "runtime.a:5,runtime.c:1"
    assert shared[0]["origins"] == "act-1/x/frame:5,act-2/y/user:send:1"


def test_a_rollup_record_is_cheap_enough_to_stay_on():
    """Measured: well under 20 microseconds a record on this box (a request costs milliseconds)."""

    rollup = LaneRollup(window_s=3600)
    started = time.perf_counter()
    for index in range(20_000):
        rollup.record("read", f"runtime.m{index % 9}", f"act-{index % 50}/c/frame", 3, 7, now=1000.0)
    per_record_us = (time.perf_counter() - started) / 20_000 * 1e6
    assert per_record_us < 20, per_record_us


def test_a_deferral_outside_a_request_logs_no_origin():
    """A deferral made outside any request (a direct call) logs ``-``."""

    build = deferred_reply("r", "runtime.x", lambda: {})
    assert build.origin == NO_ORIGIN
