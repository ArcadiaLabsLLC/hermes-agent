"""Paging reuses native display truth without retaining a second transcript in RAM."""
import gc
import json
import tracemalloc

import pytest

from tui_gateway import recovery_history, server, session_recovery
from tui_gateway.recovery_history_delivery import HistoryDeliveries, HistoryDelivery
from tests.tui_gateway.test_native_recovery_snapshot import owner, read_history  # noqa: F401


@pytest.fixture(autouse=True)
def deliveries(monkeypatch):
    cache = HistoryDeliveries(capacity=2)
    monkeypatch.setattr(recovery_history, "_deliveries", cache)
    yield cache
    for key in list(cache._entries):
        cache.discard(key[0])


def test_recovery_projects_once_and_retries_pages_without_reloading(owner, monkeypatch):
    session, db = owner
    text = "🌍 answer\n" * 100000 + "end"
    db.append_message("stored", "assistant", text)
    position = session_recovery.recover(server, "live", session)["history"]
    project, calls = server._history_to_messages, []

    def observed(*args, **kwargs):
        calls.append(True)
        return project(*args, **kwargs)

    monkeypatch.setattr(server, "_history_to_messages", observed)
    first = recovery_history.history_page(server, session, {"position": position})
    assert first["more"]
    assert recovery_history.history_page(server, session, {"position": position}) == first
    assert [row["text"] for row in read_history(session, position)] == [text]
    assert len(calls) == 1
    assert not recovery_history._deliveries._entries


def test_delivery_seeks_unicode_and_rejects_invalid_offsets():
    message = {"text": "🌍中文\n" * 50}
    delivery = HistoryDelivery([message])
    try:
        pieces, offset = [], 0
        while True:
            text, complete = delivery.chunk(0, offset, 7)
            pieces.append(text)
            offset += len(text)
            if complete:
                break
        assert json.loads("".join(pieces)) == message
        assert delivery.chunk(0, 3, 9)[0] == "".join(pieces)[3:12]
        for index, offset in [(1, 0), (-1, 0), (0, -1), (0, offset)]:
            with pytest.raises(ValueError):
                delivery.chunk(index, offset, 7)
    finally:
        delivery.close()
    assert delivery._data.closed and delivery._index.closed


def test_eviction_and_idle_expiry_close_disposable_files():
    now = [0]
    cache = HistoryDeliveries(capacity=1, idle_seconds=10, clock=lambda: now[0])
    held = []

    def render(delivery):
        held.append(delivery)
        return {"more": True}

    first, second = object(), object()
    cache.read((first,), lambda: [{"text": "first"}], render)
    cache.read((second,), lambda: [{"text": "second"}], render)
    assert held[0]._data.closed
    now[0] = 11
    cache.prune()
    assert held[1]._data.closed and not cache._entries
    cache.read((first,), lambda: [{"text": "rebuilt"}], render)
    assert held[2].chunk(0, 0, 100)[0] == '{"text":"rebuilt"}'
    cache.discard(first)
    assert held[2]._data.closed and not cache._entries


@pytest.mark.parametrize("change", ["rewrite", "retire"])
def test_changed_native_history_cannot_publish_a_stale_page(owner, monkeypatch, change):
    session, db = owner
    db.append_message("stored", "assistant", "answer" * 100000)
    position = session_recovery.recover(server, "live", session)["history"]
    project = server._history_to_messages

    def changed(*args, **kwargs):
        messages = project(*args, **kwargs)
        session["history_version" if change == "rewrite" else "_closing"] = 1
        return messages

    monkeypatch.setattr(server, "_history_to_messages", changed)
    assert recovery_history.history_page(server, session, {"position": position})["reset"]
    assert not recovery_history._deliveries._entries


def test_native_teardown_discards_abandoned_delivery(owner, monkeypatch):
    session, db = owner
    db.append_message("stored", "assistant", "answer" * 100000)
    position = session_recovery.recover(server, "live", session)["history"]
    assert recovery_history.history_page(server, session, {"position": position})["more"]
    delivery = next(iter(recovery_history._deliveries._entries.values()))[1]
    monkeypatch.setattr(server, "_teardown_session", lambda *args, **kwargs: None)
    assert server._teardown_popped_session(session, end_reason="tui_shutdown")
    assert delivery._data.closed and not recovery_history._deliveries._entries


def test_existing_reaper_expires_abandoned_delivery(monkeypatch, deliveries):
    now = [0]
    deliveries._clock = lambda: now[0]
    held = []
    deliveries.read((object(),), lambda: [{"text": "answer"}],
        lambda delivery: held.append(delivery) or {"more": True})
    now[0] = 61
    monkeypatch.setattr(server, "_sessions", {})
    for name in ("_flush_dirty_sessions", "_repair_missing_ws_orphan_reaps",
                 "_enforce_session_cap", "_reclaim_orphaned_leases"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(server, "_sessions_quiescent", lambda: False)
    server._reap_idle_sessions()
    assert held[0]._data.closed and not deliveries._entries


def test_many_abandoned_reads_keep_bounded_retained_memory():
    cache = HistoryDeliveries(capacity=2)
    text = "payload" * 100000
    tracemalloc.start()
    try:
        for _ in range(64):
            cache.read((object(),), lambda: [{"text": text}], lambda _: {"more": True})
        gc.collect()
        assert len(cache._entries) == 2
        assert tracemalloc.get_traced_memory()[0] < 1024 * 1024
    finally:
        tracemalloc.stop()
        for key in list(cache._entries):
            cache.discard(key[0])
