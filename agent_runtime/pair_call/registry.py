"""At most one call per pair of devices, kept by a rule both sides compute the same way.

Row ``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST`` (owner
2026-11-23: "whatever can open it should open it" / "both devices should try"). Both engines of a pair
dial each other, so two calls can pass their hellos at once. Each side's registry then keeps the call
whose DIALER has the lower install id (plain string order of the two proven ids, which both sides hold)
and closes the other ``duplicate_call``; both sides hold the same two ids, so both keep the same call. Two
calls from the same dialer are a redial over a call that has not noticed its drop yet: the newer is kept.

A dialer reads the registry before each dial: while a call to its far install is up it waits for that
call to end, so after a drop the first side to connect is the call and the rule above settles a tie.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .call import PairCall, emit_quietly

__layer__ = "stores"

__all__ = ["DUPLICATE_CALL", "CallRegistry", "kept_call"]

DUPLICATE_CALL = "duplicate_call"


def kept_call(held: PairCall, arriving: PairCall) -> PairCall:
    """Which of two calls to one far install both sides keep."""

    if held.dialer_install != arriving.dialer_install:
        # MUTATION: return ``arriving`` here (keep the later call) and test_pair_call's
        # test_two_engines_that_dial_each_other_keep_the_lower_dialers_call keeps the wrong call
        # when the higher id dials second; MUTATION: ``max`` for ``min`` (the ids in opposite order)
        # and the same test keeps the higher dialer's call.
        return min(held, arriving, key=lambda call: call.dialer_install)
    return arriving


class CallRegistry:
    """One serve's calls, by far install id."""

    def __init__(self, *, log: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._log = log
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._calls: dict[str, PairCall] = {}
        #: How many calls each far install has had: a new number means "re-read its state".
        self._generation: dict[str, int] = {}

    def add(self, call: PairCall) -> bool:
        """Hold *call* unless a call to the same far install is kept instead. True when it is held."""

        far = call.far.install_id
        with self._lock:
            held = self._calls.get(far)
            if held is not None and held.is_open:
                keep = kept_call(held, call)
                loser = call if keep is held else held
            else:
                keep, loser = call, None
            if keep is call:
                self._calls[far] = call
                self._generation[far] = self._generation.get(far, 0) + 1
            self._changed.notify_all()
        call.on_close(self._forget)
        if loser is not None:
            emit_quietly(self._log, {"event": "pair_call_duplicate", "far_install": far, "kept": keep.call_id,
                        "closed": loser.call_id})
            loser.close(DUPLICATE_CALL)
        if keep is call:
            emit_quietly(self._log, {"event": "pair_call_up", "far_install": far, "call": call.call_id,
                        "dialer_install": call.dialer_install, "generation": self._generation[far]})
        return keep is call

    def get(self, far_install: str) -> PairCall | None:
        with self._lock:
            call = self._calls.get(str(far_install))
        return call if call is not None and call.is_open else None

    def generation(self, far_install: str) -> int:
        with self._lock:
            return self._generation.get(str(far_install), 0)

    def wait_change(self, far_install: str, timeout: float) -> None:
        """Block until a call to *far_install* is added or ends, or *timeout* passes."""

        with self._changed:
            call = self._calls.get(str(far_install))
            if call is not None and call.is_open:
                self._changed.wait(timeout)

    def describe(self) -> list[dict[str, Any]]:
        with self._lock:
            calls = [(far, call) for far, call in self._calls.items() if call.is_open]
            generation = dict(self._generation)
        return [{**call.describe(), "generation": generation.get(far, 0)} for far, call in calls]

    def close(self, reason: str = "shutdown") -> None:
        with self._lock:
            calls = list(self._calls.values())
            self._calls.clear()
            self._changed.notify_all()
        for call in calls:
            call.close(reason)

    def _forget(self, call: PairCall) -> None:
        with self._lock:
            if self._calls.get(call.far.install_id) is call:
                self._calls.pop(call.far.install_id, None)
            self._changed.notify_all()
