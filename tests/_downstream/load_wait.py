"""ONE load-scaled wait for hermes' own tests (FH-ONE-LOAD-SCALED-WAIT, task check-budgets-count-work).

A test that waits on real work — a worker thread, a child process, a room settling — keeps a
deadline, but a deadline measured on a quiet box is a bet against the box's load: the fork's timing
flakes (RT-FLAKE-*-UNDER-LOAD) were green alone and red at load 24-100. :func:`wait_for` waits on a
condition (polled) or an event (waited), and stretches its *budget* by the box's load factor:

    from tests._downstream.load_wait import wait_for, async_wait_for

    wait_for(lambda: worker.done, 5, what="worker finished")   # the predicate's truthy value
    wait_for(started_event, 2)                                  # a threading.Event: True
    await async_wait_for(lambda: adapter.sent, 5)

The **load factor** is ``1-min load / logical CPUs`` (never below 1), or ``HERMES_TEST_LOAD_FACTOR``
when the run declares a higher one; it is read when the wait starts and again when the first
deadline passes, so a spike mid-wait still counts. The stretch is capped at :data:`MAX_FACTOR` times
the budget: a real hang still fails, naming what never happened, the budget, the factor and the load.
A fast run returns in milliseconds whatever the budget.

``tests/agent_runtime/test_bare_deadline_lint.py`` refuses a new bare ``monotonic() + N`` deadline in
the fork's own tests (FH-BARE-DEADLINE-LINT); this is what they use instead.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

LOAD_FACTOR_ENV = "HERMES_TEST_LOAD_FACTOR"
#: The hang guard: no wait stretches past this many times its budget, however loaded the box.
MAX_FACTOR = 8.0
DEFAULT_INTERVAL = 0.01


def _cpus() -> int:
    try:
        return len(os.sched_getaffinity(0)) or 1
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def _load1() -> float | None:
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):  # Windows has no load average
        return None


def load_factor() -> float:
    """How much slower than idle this box runs now: ``load1 / cpus``, the declared factor, at least 1."""
    measured = 1.0
    load = _load1()
    if load is not None:
        measured = load / _cpus()
    try:
        declared = float(os.environ.get(LOAD_FACTOR_ENV) or 1.0)
    except ValueError:
        declared = 1.0
    return min(MAX_FACTOR, max(1.0, measured, declared))


def _timed_out(what: str | None, budget: float, factor: float, waited: float) -> AssertionError:
    load = _load1()
    return AssertionError(
        f"timed out after {waited:.1f}s waiting for {what or 'the condition'} "
        f"(budget {budget}s x load factor {factor:.1f}; load1 {'n/a' if load is None else f'{load:.1f}'} "
        f"on {_cpus()} cpus)")


class _Deadline:
    """The stretched deadline: budget x factor from the start, re-read once it passes, capped."""

    def __init__(self, budget: float) -> None:
        self.budget, self.start = float(budget), time.monotonic()
        self.factor = load_factor()

    def remaining(self) -> float:
        waited = time.monotonic() - self.start
        if waited < self.budget * self.factor:
            return self.budget * self.factor - waited
        self.factor = max(self.factor, load_factor())  # the box got busier mid-wait
        return max(0.0, self.budget * self.factor - waited)

    def expired(self, what: str | None) -> AssertionError:
        return _timed_out(what, self.budget, self.factor, time.monotonic() - self.start)


def _is_event(target: Any) -> bool:
    return callable(getattr(target, "wait", None)) and callable(getattr(target, "is_set", None))


def wait_for(target: Callable[[], T] | Any, budget: float = 10.0, *, interval: float = DEFAULT_INTERVAL,
             what: str | None = None) -> T:
    """Return *target*'s first truthy value (a predicate), or True once *target* is set (an event);
    raise AssertionError when the load-scaled *budget* runs out."""
    deadline = _Deadline(budget)
    if _is_event(target):
        while not target.wait(deadline.remaining()):
            if deadline.remaining() <= 0:
                raise deadline.expired(what)
        return True  # type: ignore[return-value]
    while True:
        value = target()
        if value:
            return value
        if deadline.remaining() <= 0:
            raise deadline.expired(what)
        time.sleep(interval)


async def async_wait_for(target: Callable[[], T | Awaitable[T]] | Any, budget: float = 10.0, *,
                         interval: float = DEFAULT_INTERVAL, what: str | None = None) -> T:
    """:func:`wait_for` on an event loop: an ``asyncio.Event``, or a predicate (sync or async) polled
    with ``asyncio.sleep`` between tries."""
    deadline = _Deadline(budget)
    if isinstance(target, asyncio.Event):
        while True:
            try:
                await asyncio.wait_for(target.wait(), timeout=deadline.remaining())
                return True  # type: ignore[return-value]
            except TimeoutError:
                if deadline.remaining() <= 0:
                    raise deadline.expired(what) from None
    while True:
        value = target()
        if inspect.isawaitable(value):
            value = await value
        if value:
            return value
        if deadline.remaining() <= 0:
            raise deadline.expired(what)
        await asyncio.sleep(interval)
