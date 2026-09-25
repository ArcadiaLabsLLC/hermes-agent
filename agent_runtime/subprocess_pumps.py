"""The child-process pipe pumps: ONE owner for draining a pipe and releasing its reader.

Program §3.1d helper owner (``agent_runtime/subprocess_pumps``), created by lane
2B-C for ``tools/agent_chat_dispatch``; ``persona_chat_actor_prewarm`` and
``persona_prewarm`` fold their ``_drain`` copies in their own lanes. ``sink`` is
anything with ``append(text)`` — the dispatch lane passes a tail-keeping bound
(``tools/agent_chat_dispatch/child.py::_BoundedTail``).

Known defect, filed (runtime-queue, lane 2B-C): :func:`release_pumps`' forced
arm closes a read handle a pump is blocked on, which HANGS on Windows.
"""

from __future__ import annotations

import threading
from typing import Any

__layer__ = "policy"

__all__ = ["drain", "release_pumps"]


def drain(stream, sink: Any) -> threading.Thread:
    """Consume a child pipe for its WHOLE lifetime on a daemon thread.

    Both pipes get one of these, always. A stderr pipe nobody reads fills its OS
    buffer and wedges the child mid-write — a hang that looks exactly like a slow
    turn, and the standing reason this repo requires draining both streams
    rather than only the one being parsed.
    """

    def _pump() -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                sink.append(line)
        except Exception:  # pragma: no cover - pipe torn down under us
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    return thread


def release_pumps(proc, threads) -> None:
    """Join the pumps, then force them loose if a survivor still holds the pipe.

    ``readline`` blocks until EOF, and EOF only arrives when every writer has
    closed. A grandchild that inherited the pipe — which is exactly what "go run
    the suite" spawns — or a tree member that survived the kill keeps it open,
    so a plain join leaks two daemon threads PER DISPATCH, permanently, inside a
    process that is meant to run for days.

    Closing the parent's handle unblocks the reader (it raises, and the pump
    swallows it), which bounds the thread even when the pipe does not close on
    its own. Best effort by contract: a thread that still will not budge is one
    leak, not a growing one, and never a failed dispatch.
    """

    for thread in threads:
        thread.join(timeout=10)
    if not any(thread.is_alive() for thread in threads):
        return
    for stream in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
        try:
            if stream is not None and not stream.closed:
                stream.close()
        except Exception:
            pass
    for thread in threads:
        thread.join(timeout=2)
