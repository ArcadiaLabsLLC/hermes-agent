"""``store_events.emit_store_event`` — the one domain-event append every store spends.

Two promises, each checked with a positive control beside it: an absent (``None``)
field is not written, so a gestureless office event stays byte-identical to one
from before the gesture token existed; and a failed append never fails the write
it follows.
"""

from __future__ import annotations

import logging

from agent_runtime.office_store import OfficeStore
from agent_runtime.store_events import emit_store_event


class _Log:
    def __init__(self, *, fail: bool = False) -> None:
        self.events = []
        self.fail = fail

    def append(self, event) -> None:
        if self.fail:
            raise OSError("event log unwritable")
        self.events.append(event)


def test_a_none_field_is_dropped_and_a_real_one_is_kept():
    log = _Log()
    emit_store_event(log, "office.actor.upserted", {"actor_key": "qa", "correlation_id": None}, domain="office")
    body = log.events[0].payload
    assert body == {"actor_key": "qa"}  # positive control: the real field survives
    assert "correlation_id" not in body


def test_a_failed_append_is_logged_not_raised(caplog):
    with caplog.at_level(logging.WARNING, logger="agent_runtime.store_events"):
        emit_store_event(_Log(fail=True), "office.actor.upserted", {"actor_key": "qa"}, domain="office")
    assert "office event append failed: office.actor.upserted" in caplog.text


def test_a_gestureless_office_event_carries_no_correlation_key(isolate_agent_runtime_root):
    log = _Log()
    store = OfficeStore(log)
    store._emit("office.surface.created", None, workspace_id="ws_a")
    store._emit("office.surface.created", "gesture-1", workspace_id="ws_b")
    first, second = (event.payload for event in log.events)
    assert first == {"workspace_id": "ws_a"}
    assert second["workspace_id"] == "ws_b" and "gesture-1" in second.values()  # positive control


def test_a_schema_nullable_key_keeps_its_none_and_no_other_does():
    log = _Log()
    emit_store_event(log, "gateway.peer.reachability",
                     {"peer_install_id": "p", "unreachable_since": None, "error": None},
                     domain="gateway_peers", keep_none=frozenset({"unreachable_since"}))
    assert log.events[0].payload == {"peer_install_id": "p", "unreachable_since": None}


def test_the_peer_emitter_writes_through_the_one_rule(monkeypatch):
    """The fold: ``_emit_peer_event`` keeps the nullable ``unreachable_since`` and drops
    any other None, exactly as ``emit_store_event`` does for every store."""
    from agent_runtime.gateway_peers import trust_store

    log = _Log()
    monkeypatch.setattr("agent_runtime.events.EventLog", lambda *a, **k: log)
    trust_store._emit_peer_event("gateway.peer.reachability",
                                 {"peer_install_id": "p", "unreachable_since": None, "grant_id": None})
    assert log.events[0].payload == {"peer_install_id": "p", "unreachable_since": None}
