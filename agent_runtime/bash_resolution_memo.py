"""Fork-owned: a bash that resolved once is not re-probed for every local-backend command.

Ledger row ``tools/environments/local.py``: ``_find_bash`` (upstream) calls ``pm.shell.bash()``,
which proves each Windows candidate with a ``bash -c "exit 0"`` spawn on EVERY call, so every
terminal command cost two bash spawns (~0.3 s each, lane r-state 2026-10-18). The seam rebinds
``_find_bash`` through :func:`memoize_find_bash` at the module's import.

The memo keeps only an answer ``_find_bash`` RETURNED (a miss raises and is never cached), keyed
on what the resolution reads from the process -- the resolver function itself, ``PATH``,
``HERMES_GIT_BASH_PATH`` and the pm root variables -- and every hit re-checks that the path is
still a file. A bash installed later under the same key is picked up by the next process.
:func:`clear` drops it (the test chain calls it per test). Pinned by
``tests/tools/test_bash_resolution_memo.py``.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

__layer__ = "policy"
__all__ = ["clear", "memoize_find_bash"]

_KEY_VARIABLES = ("PATH", "HERMES_GIT_BASH_PATH", "HERMES_HOME", "HERMES_RUNTIME_DIR", "HERMES_INSTALL_ROOT")
_RESOLVED: dict[tuple, str] = {}
_LOCK = threading.Lock()


def clear() -> None:
    with _LOCK:
        _RESOLVED.clear()


def memoize_find_bash(find: Callable[[], str]) -> Callable[[], str]:
    """``find`` called again only when its key changes or the remembered bash is gone."""
    if getattr(find, "__fork_memo__", False):
        return find

    def _find_bash() -> str:
        import pm.shell

        key = (pm.shell.bash, *(os.environ.get(name) for name in _KEY_VARIABLES))
        with _LOCK:
            hit = _RESOLVED.get(key)
        if hit is not None and os.path.isfile(hit):
            return hit
        bash = find()
        with _LOCK:
            _RESOLVED[key] = bash
        return bash

    _find_bash.__doc__ = find.__doc__
    _find_bash.__wrapped__ = find  # type: ignore[attr-defined]
    _find_bash.__fork_memo__ = True  # type: ignore[attr-defined]
    return _find_bash
