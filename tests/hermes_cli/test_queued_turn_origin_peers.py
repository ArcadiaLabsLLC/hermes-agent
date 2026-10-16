"""The queued-turn peer map is bounded: a detached or stale peer is never kept (L5.14)."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from agent_runtime.chat_root_send_queue import ORIGIN_ARG
from hermes_cli.harness_parts.serve import queued_turn_origin as origin


class _Sink:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    def emit(self, frame: dict) -> None:
        self.frames.append(frame)


def _session(**sinks):
    return SimpleNamespace(connection_sinks_lock=threading.Lock(), connection_sinks=dict(sinks))


def _gateway_entry(owner: str):
    return SimpleNamespace(args={ORIGIN_ARG: {"owner": owner, "gateway": True}})


def _peers(session) -> dict:
    return getattr(session, origin._PEERS_ATTR)


def test_a_remembered_peer_gets_its_settle_once():
    sink = _Sink()
    session = _session(dev=sink)
    assert origin.queued_turn_peer(session, _gateway_entry("dev"), "rid-1") is sink
    assert origin.deliver_to_queued_peer(session, {"request_id": "rid-1"}) == 1
    assert origin.deliver_to_queued_peer(session, {"request_id": "rid-1"}) == 0
    assert sink.frames == [{"request_id": "rid-1"}]


def test_a_peer_whose_connection_detached_is_dropped_on_the_next_access():
    gone, other = _Sink(), _Sink()
    session = _session(dev=gone, other=other)
    origin.queued_turn_peer(session, _gateway_entry("dev"), "rid-requeued")
    with session.connection_sinks_lock:
        del session.connection_sinks["dev"]
    origin.queued_turn_peer(session, _gateway_entry("other"), "rid-2")
    assert "rid-requeued" not in _peers(session), "a detached device's sink stays referenced"
    assert "rid-2" in _peers(session)


def test_a_peer_older_than_the_ttl_is_dropped(monkeypatch):
    stale, fresh = _Sink(), _Sink()
    session = _session(dev=stale, other=fresh)
    clock = [1000.0]
    monkeypatch.setattr(origin.time, "monotonic", lambda: clock[0])
    origin.queued_turn_peer(session, _gateway_entry("dev"), "rid-never-settled")
    clock[0] += origin.QUEUED_PEER_TTL_SECONDS + 1
    assert origin.deliver_to_queued_peer(session, {"request_id": "rid-other"}) == 0
    assert "rid-never-settled" not in _peers(session)


def test_a_live_peer_inside_the_ttl_is_kept():
    """Positive control for the two drops above: attached and fresh survives a prune."""

    sink, other = _Sink(), _Sink()
    session = _session(dev=sink, other=other)
    origin.queued_turn_peer(session, _gateway_entry("dev"), "rid-live")
    origin.queued_turn_peer(session, _gateway_entry("other"), "rid-2")
    assert "rid-live" in _peers(session)
