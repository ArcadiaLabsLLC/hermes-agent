"""``ran_by`` — which edition, commit and code tree ran a turn (row ``RT-TURN-EDITION-STAMP``).

Plan ``docs/agent-runtime-harness/planned/naming-and-address-map-2026-10-25.md`` ruling 9: editions are
not an address segment — the data is the same whichever edition reads it — so every turn record carries
the edition (``developer`` / ``bundled``, from the install stamp :func:`store_epoch.provenance` reads),
the commit and the code-tree digest (:mod:`agent_runtime.build_stamp`, RS-6) of the process that ran it.

Resolved once per process (the build stamp is itself cached; the edition cannot change while it lives).
Never raises: a value that could not be measured is ``None``, never a guess.
"""

from __future__ import annotations

import threading
from typing import Any

__layer__ = "stores"

_lock = threading.Lock()
_cached: dict[str, Any] | None = None


def ran_by() -> dict[str, Any]:
    """``{edition, commit, code_tree}`` of this process."""

    global _cached
    with _lock:
        if _cached is None:
            _cached = _resolve()
        return dict(_cached)


def reset_ran_by_cache() -> None:
    """Tests only: a live process's provenance does not change."""

    global _cached
    with _lock:
        _cached = None


def _resolve() -> dict[str, Any]:
    edition: str | None = None
    commit: str | None = None
    code_tree: str | None = None
    try:
        from .store_epoch import provenance

        stamp = provenance()
        edition, commit = stamp.get("edition"), stamp.get("commit")
    except Exception:
        pass
    try:
        from .build_stamp import build_stamp

        build = build_stamp()
        commit = build.commit or commit
        code_tree = build.code_tree
    except Exception:
        pass
    return {"edition": edition, "commit": commit, "code_tree": code_tree}
