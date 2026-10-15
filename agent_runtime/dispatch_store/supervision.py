"""Which dispatches a live supervisor in THIS process still answers for.

The process-local registry the tools lane's supervisors write
(``tools/agent_chat_dispatch/local.py`` marks and forgets) and the orphan sweep
reads (``db._supervised_here``). It lives in the store package so the store
reads it DOWNWARD: the sweep's question used to be answered by a lazy import of
the tools lane, an upward edge from ``stores`` to ``lanes`` (W0-G6).
"""

from __future__ import annotations

import threading

__layer__ = "stores"

__all__ = [
    "_forget_supervised",
    "_mark_supervised",
    "_supervised",
    "_supervised_lock",
    "supervised_dispatch_ids",
]


#: Dispatch ids this process is actively supervising — and the guard that keeps
#: the orphan sweep from answering for them.
#:
#: The sweep became PERIODIC in the previous commit, which turned a theoretical
#: second writer into a real one: from the instant a child exits until this
#: supervisor's ``record_completion`` lands — across ``proc.wait()`` and two
#: pump joins — the sweep sees a dead PID on a ``running`` row and settles it
#: ``unknown``. The 5s drain then delivers "the outcome is unknown" for a
#: dispatch that COMPLETED, and the supervisor's real answer, written moments
#: later, is absorbed by the delivery-turn replay dedup — so the sender is told
#: nothing is known and never receives the answer sitting in the row.
#:
#: A row still supervised HERE is not an orphan by definition, so the sweep
#: skips it. Process-local on purpose, and sufficient: the race is between two
#: threads of one serve process, and a row whose supervisor died is exactly the
#: row the sweep SHOULD settle.
_supervised: set[str] = set()
_supervised_lock = threading.Lock()


def _mark_supervised(dispatch_id: str) -> None:
    with _supervised_lock:
        _supervised.add(str(dispatch_id))


def _forget_supervised(dispatch_id: str) -> None:
    with _supervised_lock:
        _supervised.discard(str(dispatch_id))


def supervised_dispatch_ids() -> set[str]:
    """A snapshot of every dispatch this process is actively supervising.

    The orphan sweep reads this to know which ``running`` rows are not orphans
    at all. Returns a COPY: the sweep iterates while supervisors come and go,
    and handing out the live set would make that a mutation-during-iteration
    bug on a background thread.
    """

    with _supervised_lock:
        return set(_supervised)
