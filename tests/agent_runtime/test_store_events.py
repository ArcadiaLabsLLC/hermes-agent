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
