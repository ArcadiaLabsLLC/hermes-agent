"""Hand a settled provider stream's connection back to the pool instead of dropping it.

h-conn-pool (``Harness_Brain/20 — Active Initiatives/runtime-queue.md``, the
turns 2-3 reconnect row). httpcore returns an HTTP/1.1 connection to its pool
only when the response body was read to its end; a response closed mid-body
closes its connection. A Responses SSE stream sends its terminal event
(``response.completed``) BEFORE the body ends (the chunked terminator follows),
so a consumer that stops at the terminal event and closes the stream throws the
connection away.

The chat turn already reads past the terminal event
(``agent/codex_runtime.py::run_codex_stream``'s post-terminal drain). The
auxiliary Codex adapter (``agent/auxiliary_client.py::_CodexCompletionsAdapter``
-- the title call after a chat's first turns) did not: it took the warm
connection the turn had just returned to the process-shared pool, closed it
mid-body, and the next turn opened a new TLS connection (Neko chats
``a103277369f5`` and ``323d4f079037``, turns 2 and 3).

:func:`drain_settled_stream` reads what is left, bounded the way upstream bounds
the turn's own drain (a daemon reader and a wait; on expiry the caller's close
aborts the connection exactly as before). Fail-open: it never raises.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: How long the caller waits for the rest of a settled stream. The rest is one
#: chunked terminator on every record; a relay that holds the socket open after
#: the terminal event costs this much, once, and then loses the connection.
DRAIN_BUDGET_SECONDS = 2.0


def drain_settled_stream(stream: Any, *, budget: float = DRAIN_BUDGET_SECONDS) -> bool:
    """Read *stream* to its end on a daemon thread; True when it ended within *budget*.

    *stream* is an iterable whose terminal event the caller already consumed. A
    False return changes nothing for the caller: it closes the stream as it
    always did, and the connection is dropped as it always was.
    """

    if stream is None or not callable(getattr(stream, "__iter__", None)):
        return False
    ended = threading.Event()
    outcome = {"ended": False}

    def _read_rest() -> None:
        try:
            for _ignored in stream:
                pass
            outcome["ended"] = True
        except Exception:
            logger.debug("settled stream drain stopped early", exc_info=True)
        finally:
            ended.set()

    try:
        threading.Thread(target=_read_rest, name="settled-stream-drain", daemon=True).start()
        return ended.wait(max(0.0, float(budget))) and outcome["ended"]
    except Exception:
        logger.debug("settled stream drain not started", exc_info=True)
        return False


__all__ = ["DRAIN_BUDGET_SECONDS", "drain_settled_stream"]
