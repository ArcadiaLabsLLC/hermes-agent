"""FH-ONE-LOAD-SCALED-WAIT: ``tests._downstream.load_wait`` stretches a wait's budget by the box's load.

The planted busy-box wait is the mutation's red: the condition comes true at 0.4 s, the budget is
0.15 s and the box reads 4x loaded, so the scaled wait (0.6 s) passes where the bare budget fails.
Killing mutation (recorded in the commit): ``_Deadline.__init__`` sets ``self.factor = 1.0`` and
``remaining`` stops re-reading it -> ``test_a_busy_box_stretches_the_budget`` raises AssertionError.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from tests._downstream import load_wait


def _box(monkeypatch, *, load1: float | None, cpus: int = 4) -> None:
    monkeypatch.setattr(load_wait, "_load1", lambda: load1)
    monkeypatch.setattr(load_wait, "_cpus", lambda: cpus)
    monkeypatch.delenv(load_wait.LOAD_FACTOR_ENV, raising=False)


def _true_after(seconds: float):
    start = time.monotonic()
    return lambda: time.monotonic() - start >= seconds


def test_a_busy_box_stretches_the_budget(monkeypatch):
    _box(monkeypatch, load1=16.0)
    assert load_wait.wait_for(_true_after(0.4), 0.15, what="the planted work") is True


def test_an_idle_box_keeps_the_budget_and_names_what_never_happened(monkeypatch):
    _box(monkeypatch, load1=0.5)
    with pytest.raises(AssertionError, match=r"the planted work .*budget 0.15s x load factor 1.0"):
        load_wait.wait_for(_true_after(5), 0.15, what="the planted work")


def test_the_stretch_is_capped_so_a_hang_still_fails(monkeypatch):
    _box(monkeypatch, load1=4000.0)
    assert load_wait.load_factor() == load_wait.MAX_FACTOR
    with pytest.raises(AssertionError, match="load factor 8.0"):
        load_wait.wait_for(lambda: False, 0.02)


def test_a_declared_factor_raises_the_floor_and_windows_has_no_load(monkeypatch):
    _box(monkeypatch, load1=None)
    assert load_wait.load_factor() == 1.0
    monkeypatch.setenv(load_wait.LOAD_FACTOR_ENV, "3")
    assert load_wait.load_factor() == 3.0


def test_a_load_spike_mid_wait_is_read_when_the_first_deadline_passes(monkeypatch):
    loads = iter([0.0] + [16.0] * 1000)
    monkeypatch.setattr(load_wait, "_load1", lambda: next(loads))
    monkeypatch.setattr(load_wait, "_cpus", lambda: 4)
    monkeypatch.delenv(load_wait.LOAD_FACTOR_ENV, raising=False)
    assert load_wait.wait_for(_true_after(0.3), 0.15) is True


def test_an_event_is_waited_and_the_predicate_value_is_returned(monkeypatch):
    _box(monkeypatch, load1=0.0)
    event = threading.Event()
    threading.Timer(0.05, event.set).start()
    assert load_wait.wait_for(event, 2) is True
    assert load_wait.wait_for(lambda: {"row": 1}, 1) == {"row": 1}


def test_the_async_wait_takes_an_asyncio_event_and_an_async_predicate(monkeypatch):
    _box(monkeypatch, load1=0.0)

    async def main():
        event = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, event.set)
        assert await load_wait.async_wait_for(event, 2) is True

        async def ready():
            return "sent"

        assert await load_wait.async_wait_for(ready, 1) == "sent"
        with pytest.raises(AssertionError, match="the reply"):
            await load_wait.async_wait_for(lambda: False, 0.05, what="the reply")

    asyncio.run(main())
