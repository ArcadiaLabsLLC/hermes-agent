"""A ``mode=ro`` open of a WAL store in a directory this process cannot write.

Fork-owned (RT-SESSIONS-EXPORT-HOME-WRITES). SQLite opens a WAL-mode database
read-only only when its ``-shm`` and ``-wal`` files exist or can be created
(https://www.sqlite.org/wal.html#readonly). In a home whose directory is not
writable — the launcher's owner-chat import reads the owner's store from
another account — neither can be created, and the first SELECT fails with
"attempt to write a readonly database".

When the directory is not writable AND no ``-wal`` file exists, the store is
fully checkpointed and no WAL writer is attached (a WAL writer keeps its
``-wal`` while connected), so ``immutable=1`` reads the file as it stands
without asking SQLite for the shared-memory index. Any other case keeps the
plain ``mode=ro`` URI, so a writable home is byte-identical to upstream.

``hermes_state`` rebinds its ``read_only_db_uri`` through :func:`snapshot_when_unwritable`
(one ``# fork seam`` line); upstream PR candidate: the same branch inside
``hermes_state_holders.read_only_db_uri``.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Callable

IMMUTABLE_PARAM = "&immutable=1"


def needs_immutable_open(db_path) -> bool:
    """True when ``mode=ro`` cannot attach: the directory is unwritable and no ``-wal`` exists."""
    path = Path(db_path)
    directory = path.resolve().parent
    if os.access(directory, os.W_OK):
        return False
    return not Path(f"{path}-wal").exists()


def snapshot_when_unwritable(uri_for: Callable[[object], str]) -> Callable[[object], str]:
    """Wrap a ``mode=ro`` URI builder so an unwritable, checkpointed store opens ``immutable``."""

    @functools.wraps(uri_for)
    def _uri(db_path) -> str:
        uri = uri_for(db_path)
        return uri + IMMUTABLE_PARAM if needs_immutable_open(db_path) else uri

    return _uri
