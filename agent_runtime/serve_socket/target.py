"""Resolving WHERE a client connects: ``SocketTarget`` and
``resolve_socket_target`` over the owner record and the serve registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_runtime.serve_socket.vocabulary import SOCKET_HOST
from agent_runtime.serve_socket.owner_lock import read_socket_owner
from agent_runtime.serve_socket.wire import _int_or_none

__layer__ = "stores"

__all__ = [
    "CLASSIFICATION_OWNER_FILE_UNVERIFIED",
    "SocketTarget",
    "_target_from_row",
    "resolve_socket_target",
]


# ── discovery + client ───────────────────────────────────────────────────────


#: What the owner sidecar can honestly claim about liveness: nothing. It is
#: written by the lock holder and is precise while that process lives, and it
#: cannot prove the process still does. Never ``None`` any more — a null
#: classification read as "no objection" at exactly the call site that had to
#: object.
CLASSIFICATION_OWNER_FILE_UNVERIFIED = "unverified_owner_file"


@dataclass(frozen=True, slots=True)
class SocketTarget:
    """Where the socket service for a root is, and how confidently we know."""

    host: str
    port: int
    pid: int | None
    boot_id: str | None
    #: ``registry`` (an entry the registry classified) or ``owner_file`` (the
    #: sidecar, when the registry could not answer).
    source: str
    #: The registry's read-time classification, or
    #: ``unverified_owner_file`` when the sidecar was the source. ``live`` is
    #: the only value that is evidence of a process; everything else is why a
    #: connect may fail — and, before this was enforced, why a client could
    #: hand its credential to whatever had taken over a dead serve's port.
    classification: str

    @property
    def live(self) -> bool:
        return self.classification == "live"

    def payload(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "pid": self.pid,
            "boot_id": self.boot_id,
            "source": self.source,
            "classification": self.classification,
            "live": self.live,
        }


def resolve_socket_target(
    store_root: Path | str, *, probe: Any = None, allow_stale: bool = False
) -> SocketTarget | None:
    """Find the LIVE socket service for *store_root*, or None.

    The REGISTRY is the only source that classifies liveness at read time (a
    dead pid, a recycled pid, and an unreadable probe are three different
    answers there, and none of them is "live"), so a live registry row is the
    only thing this returns by default.

    That default is load-bearing. This used to fall back — ``for row in (live
    or candidates)`` — and then to the owner sidecar with no classification at
    all, so a caller asking "where is the service" got back a row the registry
    had ALREADY classified ``stale_dead_pid`` and connected to it. A dead
    serve's port is reusable by any local process, and the first cut of the
    handshake sent the raw token, so the fallback was a credential handed to an
    impostor. Both halves are closed now (the token no longer travels either),
    and the returned target still has to be live.

    ``allow_stale=True`` is the deliberate diagnostic path: it returns the best
    non-live candidate CARRYING its classification, so a caller can name what it
    is refusing ("stale_dead_pid", "unverified_owner_file") instead of reporting
    the far less useful "nothing found". A caller that passes it and then
    connects anyway has made that choice explicitly, in the open.
    """

    try:
        from ..serve_registry import CLASSIFICATION_LIVE, list_serve_instances

        rows = list_serve_instances(store_root, probe=probe)
    except Exception:
        rows = []
    candidates = [
        row
        for row in rows
        if _int_or_none(row.get("port")) and "socket" in str(row.get("transport") or "")
    ]
    live = [row for row in candidates if row.get("classification") == CLASSIFICATION_LIVE]
    for row in live:
        target = _target_from_row(row)
        if target is not None:
            return target
    if not allow_stale:
        return None
    for row in candidates:
        target = _target_from_row(row)
        if target is not None:
            return target
    owner = read_socket_owner(store_root)
    port = _int_or_none(owner.get("port"))
    if port is None:
        return None
    return SocketTarget(
        host=str(owner.get("host") or SOCKET_HOST),
        port=port,
        pid=_int_or_none(owner.get("pid")),
        boot_id=owner.get("boot_id") if isinstance(owner.get("boot_id"), str) else None,
        source="owner_file",
        classification=CLASSIFICATION_OWNER_FILE_UNVERIFIED,
    )


def _target_from_row(row: dict[str, Any]) -> SocketTarget | None:
    port = _int_or_none(row.get("port"))
    if port is None:  # pragma: no cover - callers filter on this already
        return None
    return SocketTarget(
        host=SOCKET_HOST,
        port=port,
        pid=_int_or_none(row.get("pid")),
        boot_id=row.get("boot_id") if isinstance(row.get("boot_id"), str) else None,
        source="registry",
        classification=str(row.get("classification") or "unknown"),
    )
