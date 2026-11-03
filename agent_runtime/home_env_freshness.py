"""Keep a long-lived serve's ``os.environ`` in step with the bound home's ``.env`` (RT-SERVE-STALE-ENV-AFTER-SET-KEY).

``hermes harness auth set-key`` / ``auth remove`` run in ANOTHER process and write the home ``.env``; the serve
loaded that file once at boot, so its provider reads (``runtime.provider.*``: the pool row, ``token_preview``,
``credential_source.sources.api_key.present``) and its resolver kept answering from the boot-time environment
until a restart. :func:`refresh_home_env` is called before every provider verb (``serve_rpc/provider.py::
_answer``): it stats the file and, only when its ``(mtime_ns, size, inode)`` moved since the last look, applies
the difference:

* a key the file sets to a value ``os.environ`` does not hold is written (the startup loader's ``.env`` wins
  over the shell, ``env_loader`` ``override=True``);
* a key the PREVIOUS look of the file held and the file no longer holds is removed — only while ``os.environ``
  still carries the file's old value, so a key the process was launched with and the file never named is
  never clobbered (upstream's ``reload_env`` drops every known key missing from the file; a serve started
  with a key in its environment would lose it).

The first look records the file and applies its sets only. A routed profile-home override (multiplex) skips:
that environment is not the process's to rewrite. Values are compared through a digest; none is kept.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

__layer__ = "stores"
__all__ = ["refresh_home_env", "reset_home_env_freshness"]

logger = logging.getLogger(__name__)

_lock = threading.Lock()
#: ``str(path)`` -> ``(signature, {key: value digest})`` of the last look.
_seen: dict[str, tuple[tuple[int, int, int] | None, dict[str, str]]] = {}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def _signature(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino)


def reset_home_env_freshness() -> None:
    """Forget every look (tests; a re-bound home starts over on its own key anyway)."""

    with _lock:
        _seen.clear()


def refresh_home_env() -> int:
    """Apply the home ``.env``'s change since the last look to ``os.environ``; return how many keys moved."""

    from hermes_constants import get_hermes_home_override

    if get_hermes_home_override() is not None:
        return 0
    from hermes_cli.config import get_env_path, load_env

    path = get_env_path()
    signature = _signature(path)
    key = str(path)
    with _lock:
        held = _seen.get(key)
        if held is not None and held[0] == signature:
            return 0
        values = load_env() if signature is not None else {}
        previous = held[1] if held is not None else {}
        moved = 0
        for name, value in values.items():
            if os.environ.get(name) != value:
                os.environ[name] = value
                moved += 1
        for name in set(previous) - set(values):
            current = os.environ.get(name)
            if current is not None and _digest(current) == previous[name]:
                del os.environ[name]
                moved += 1
        _seen[key] = (signature, {name: _digest(value) for name, value in values.items()})
    if moved:
        logger.info("home .env changed under the serve; %d environment key(s) refreshed", moved)
    return moved
