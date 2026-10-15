"""The charsheet package's one owner of the time stamp, the two atomic writers, the slug
helpers, and its one call-time reach into ``agent_runtime`` (ruling Q9).

Sub-100 by statement (ruling 3): it exists to retire duplicate helper copies and
a hidden module-level import, not to hold a flow.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

__layer__ = "models"


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Lowercase, hyphenate and strip *name* into one filesystem path segment."""
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "character"


def safe_segment(value: str) -> str:
    """One bare path segment — a slug/id can never escape its parent directory."""
    return Path(str(value).strip()).name


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: dict | list) -> None:
    """tmp + fsync + :func:`os.replace` — a reader never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def shared_characters_dir() -> Path:
    """``agent_runtime.profile_home.get_shared_characters_dir``, imported at CALL time.

    The package's ONE reach into ``agent_runtime`` (ruling Q9). ``agent_runtime``
    is not in the shipped wheel — the packaging boundary
    :mod:`agent.charsheet` opens with — so the reach lives here, lazily: every
    module of the package imports cleanly in a plain wheel, and only a call that
    resolves the install-wide library needs the runtime.
    """
    from agent_runtime.profile_home import get_shared_characters_dir

    return get_shared_characters_dir()
