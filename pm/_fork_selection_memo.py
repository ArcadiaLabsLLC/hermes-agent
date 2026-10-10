"""Fork-owned memo for ``pm.plugins_state.read_home_selection`` (ledger row ``pm/plugins_state.py``).

``venv_is_current`` re-reads every profile's ``config.yaml`` through ruamel, and a self-managed
launch asks it twice (``prepare_launch`` + ``check_runtime``): ~650 ms per pass over 12 homes.
The memo keys on the file's BYTES, not its stat: a write inside one clock tick with the same size
(``enable a`` then ``enable b``) defeats an mtime key, while reading a few KB is cheap next to the
parse. Errors are never cached; every hit hands back a deep copy, so a caller's edit never leaks.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Callable, Optional

Reader = Callable[[Path], Optional[dict[str, Any]]]

_MAX_ENTRIES = 64


def memoize_read_home_selection(read: Reader) -> Reader:
    """``read`` re-parsed only when the config's bytes change; delegates on anything unusual."""
    if getattr(read, "__fork_memo__", False):
        return read
    cache: dict[str, tuple[bytes, Optional[dict[str, Any]]]] = {}
    lock = threading.Lock()

    def read_home_selection(home: Path) -> Optional[dict[str, Any]]:
        key = str(home)
        try:
            raw = (Path(home) / "config.yaml").read_bytes()
        except OSError:
            return read(home)  # missing or unreadable: the reader owns the verdict
        with lock:
            hit = cache.get(key)
        if hit is not None and hit[0] == raw:
            return copy.deepcopy(hit[1])
        result = read(home)
        try:
            if (Path(home) / "config.yaml").read_bytes() != raw:
                return result  # rewritten mid-read: do not pair these bytes with that parse
        except OSError:
            return result
        with lock:
            if len(cache) >= _MAX_ENTRIES and key not in cache:
                cache.pop(next(iter(cache)))
            cache[key] = (raw, copy.deepcopy(result))
        return result

    read_home_selection.__doc__ = read.__doc__
    read_home_selection.__wrapped__ = read  # type: ignore[attr-defined]
    read_home_selection.__fork_memo__ = True  # type: ignore[attr-defined]
    return read_home_selection
