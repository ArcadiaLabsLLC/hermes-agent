"""Both sides of a pair keep trying to call each other; the first call to connect is the call.

Row ``RT-ACCOUNT-ONLY-ANY-TWO-OF-YOUR-DEVICES-SHARE-ONE-CONNECTION-WHICHEVER-OPENS-IT-FIRST`` (owner
2026-11-23: "both devices should try" / "shouldn't they both try to call"). One :class:`CallDialer` per
far install, on its own thread, on EACH side of the pair. While the registry holds a call to that install
(whoever dialled it) the dialer waits for it to end; after a drop it dials again at once, after a little
jitter, and the first side to connect holds the call (a tie is the registry's dedupe rule). A failed dial
backs off 1 s doubling to 30 s, plus jitter. ``dial_once`` is the serve's: it answers the new
:class:`~.call.PairCall` (already offered to the registry), ``"stop:<reason>"`` to give up, or any other
text to back off and try again.
"""

from __future__ import annotations

import random
import threading
from typing import Any, Callable

from .call import PairCall
from .registry import CallRegistry

__layer__ = "lanes"

__all__ = ["CallDialer"]

_BACKOFF_FIRST = 1.0
_BACKOFF_MAX = 30.0
#: How often a dialer waiting on a held call looks at its stop flag.
_HELD_POLL = 0.5


class CallDialer:
    """One far install's dial loop."""

    def __init__(self, registry: CallRegistry, far_install: str, dial_once: Callable[[], Any], *,
                 backoff_first: float | None = None, backoff_max: float | None = None,
                 jitter: Callable[[], float] = random.random) -> None:
        self._registry = registry
        self.far_install = str(far_install)
        self._dial_once = dial_once
        self._first = float(_BACKOFF_FIRST if backoff_first is None else backoff_first)
        self._max = float(_BACKOFF_MAX if backoff_max is None else backoff_max)
        self._jitter = jitter
        self._stop = threading.Event()
        self.state = "dialing"
        self.stopped_reason: str | None = None
        self.calls_made = 0
        self.last_failure: str | None = None
        self._thread = threading.Thread(target=self._run, name="pair-call-dialer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, reason: str = "hung_up") -> None:
        if not self._stop.is_set():
            self.stopped_reason = reason
        self._stop.set()

    def join(self, timeout: float) -> None:
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def status(self) -> dict[str, Any]:
        return {"far_install": self.far_install, "state": self.state, "calls_made": self.calls_made,
                "last_failure": self.last_failure, "stopped_reason": self.stopped_reason}

    def _run(self) -> None:
        backoff = self._first
        try:
            while not self._stop.is_set():
                held = self._registry.get(self.far_install)
                if held is not None:
                    self.state = "connected"
                    while held.is_open and not self._stop.is_set():
                        held.wait_closed(_HELD_POLL)
                    if self._stop.is_set():
                        break
                    # MUTATION: ``break`` here when ``not held.outbound`` (the side that accepted the
                    # call leaves the redial to the side that dialled it) and test_pair_call's
                    # test_a_killed_call_fails_its_requests_and_both_sides_redial never gets a call back.
                    self.state = "dialing"
                    backoff = self._first
                    # Both sides redial at once; the jitter spreads them, the registry settles a tie.
                    if self._stop.wait(self._jitter() * self._first * 0.5):
                        break
                    continue
                self.state = "dialing"
                outcome = self._dial_once()
                if isinstance(outcome, PairCall):
                    self.calls_made += 1
                    backoff = self._first
                    continue
                text = str(outcome or "dial_failed")
                if text.startswith("stop:"):
                    self.stopped_reason = text[5:]
                    break
                self.last_failure = text
                if self._stop.wait(backoff + self._jitter() * backoff * 0.5):
                    break
                backoff = min(self._max, backoff * 2)
        finally:
            self.state = "stopped"
