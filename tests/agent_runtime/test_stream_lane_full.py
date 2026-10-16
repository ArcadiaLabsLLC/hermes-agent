"""The standing-stream lane refuses a stream past its ceiling, typed and logged (runtime-queue WEAKNESS, c0962bfb48e).

A ``harness stream`` never returns, so the 33rd submit used to queue in the
``ThreadPoolExecutor`` behind 32 infinite ones with nothing said: it waited forever.
"""
from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest

from hermes_cli.harness_parts.serve import request_pool
from hermes_cli.harness_parts.serve.handle_message import MessageHandling
from hermes_cli.harness_parts.serve.request_pool import RequestPool, StreamLaneFull


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setattr(request_pool, "STREAM_LANE_WORKERS", 2)
    lane = RequestPool(1)
    yield lane
    lane.shutdown(wait=False)


def test_the_stream_past_the_ceiling_is_refused_and_a_finished_one_frees_its_place(pool, caplog):
    release = threading.Event()
    running = [pool.submit_stream(release.wait, 10) for _ in range(2)]
    with caplog.at_level(logging.WARNING, logger=request_pool.__name__):
        with pytest.raises(StreamLaneFull):
            pool.submit_stream(release.wait, 10)
    assert any("stream_lane_full running=2 ceiling=2" in r.getMessage() for r in caplog.records)
    release.set()
    for future in running:
        future.result(timeout=10)
    assert pool.submit_stream(lambda: "ok").result(timeout=10) == "ok"  # control: places came back


def test_the_serve_answers_a_refused_stream_with_a_typed_error(pool):
    release = threading.Event()
    held = [pool.submit_stream(release.wait, 10) for _ in range(2)]
    emitted = []
    host = SimpleNamespace(inflight_lock=threading.Lock(), drain_state=None, inflight={}, inflight_futures={},
                           pool=pool, _run=lambda request: None)
    request = SimpleNamespace(rid="r-33", key=("c", "r-33"), is_chat_turn=False, is_runtime_stream=True, accepted=None)
    try:
        MessageHandling._submit_request(host, request, SimpleNamespace(emit=emitted.append))
    finally:
        release.set()
        for future in held:
            future.result(timeout=10)
    assert emitted and emitted[0]["error"] == "stream_lane_full" and emitted[0]["id"] == "r-33"
    assert host.inflight == {}
