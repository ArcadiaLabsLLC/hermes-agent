"""The serve's request workers, and the one-handler rule for a chat turn (lane h-pool-starve).

**Two lanes, one pool object.** Every request ran on one four-worker pool, so a
chat turn queued behind whatever held the workers. On 2026-10-06 12:04 four
``harness stream`` hydrates parked on a snapshot build held all four for 83 s;
Neko turn ``b00deebf`` waited 24 s for a worker
(``chat_turn_accept_to_anchor … queue_ms=24111``), the launcher declared the
request hung and re-sent it. A reserved slot cannot be built on a
``ThreadPoolExecutor`` (a request that waits for permission still holds the
worker it waits on), and teaching every hydrate to wait without a worker is a
rewrite of the stream lane; a second executor that only chat turns use is the
smallest change that makes the guarantee unconditional: a chat turn queues
behind other chat turns and nothing else. :class:`RequestPool` keeps the one
``submit`` / ``shutdown`` face every caller already uses (the drain joins both
lanes) and adds :meth:`RequestPool.submit_turn`.

**One turn, one handler.** A turn the launcher re-sent (same
``--client-message-id``) while the first presentation still waited for a worker
used to run TWO handlers: the re-send anchored at 12:04:45.700 and the original
anchored again at 12:04:47.297. The turn journal kept that correct (the loser is
answered ``chat_turn_duplicate_in_flight`` after the lease) but only after the
second handler had paid the turn's whole preparation beside the first.
:class:`TurnClaims` refuses the second at the worker's door instead: the first
presentation of a ``(verb, client_message_id)`` to reach a worker claims it
until its exit frame; another one reaching a worker meanwhile runs no handler
and is answered ``chat_turn_duplicate_in_flight`` (re-present this id; the
journal answers once the turn settles). A presentation after the turn ended is
the journal's to answer, exactly as before.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: ``chat_turn_duplicate_refused``: a second presentation that ran no handler.
DUPLICATE_REFUSED_RECEIPT = (
    "chat_turn_duplicate_refused request=%s twin=%s verb=%s client_message_id=%s"
)
#: The code the journal's own duplicate-in-flight answer exits with.
DUPLICATE_IN_FLIGHT_EXIT_CODE = 2
_CLIENT_MESSAGE_ID_FLAG = "--client-message-id"


class RequestPool:
    """The shared request lane and the chat-turn lane, each ``size`` workers."""

    def __init__(self, size: int) -> None:
        workers = max(1, int(size))
        self.shared = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="harness-serve")
        self.turns = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="harness-serve-turn")

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        return self.shared.submit(fn, *args)

    def submit_turn(self, fn: Callable[..., Any], *args: Any) -> Future:
        return self.turns.submit(fn, *args)

    def shutdown(self, wait: bool = True) -> None:
        """Stop both lanes taking work, then (``wait``) join both."""

        self.shared.shutdown(wait=False)
        self.turns.shutdown(wait=False)
        if wait:
            self.shared.shutdown(wait=True)
            self.turns.shutdown(wait=True)


def turn_claim_key(argv: Any) -> tuple[str, str] | None:
    """``(verb, client_message_id)`` of a chat-turn argv, or ``None`` when it names no id."""

    tail = [str(item) for item in argv or ()]
    if tail and tail[0] == "harness":
        tail = tail[1:]
    verb = " ".join(tail[:2])
    for index, item in enumerate(tail):
        if item == _CLIENT_MESSAGE_ID_FLAG and index + 1 < len(tail):
            value = tail[index + 1]
        elif item.startswith(_CLIENT_MESSAGE_ID_FLAG + "="):
            value = item.split("=", 1)[1]
        else:
            continue
        return (verb, value) if value else None
    return None


class TurnClaims:
    """Which request is running each ``(verb, client_message_id)`` in this serve."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[tuple[str, str], str] = {}

    def claim(self, key: tuple[str, str] | None, rid: str) -> str | None:
        """Claim ``key`` for ``rid``; the twin's rid when another request holds it."""

        if key is None:
            return None
        with self._lock:
            holder = self._running.get(key)
            if holder is not None and holder != rid:
                return holder
            self._running[key] = rid
            return None

    def release(self, key: tuple[str, str] | None, rid: str) -> None:
        if key is None:
            return
        with self._lock:
            if self._running.get(key) == rid:
                del self._running[key]
