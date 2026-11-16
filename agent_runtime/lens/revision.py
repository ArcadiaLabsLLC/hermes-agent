"""The Lens store revision: ONE number that moves whenever the Lens store changes.

``RT-LENS-STORE-HAS-ONE-REVISION`` (Eternia ``TASK-LENS-READS-FROM-ONE-STORE``). Eternia's Lens
panels used to refresh on a dozen different cues and missed changes made elsewhere; now every Lens
answer and event carries ``store_revision``, and a panel re-reads only when it moved past the one
its data was read at.

* Every ``LensStore._db`` transaction that changed a row bumps it once, inside the same
  transaction (the store's single commit point) — monitors, observations (every poll, with no
  event), Episodes, receipts, routes, budgets, actions and every ``store_*`` module alike.
* A writer on its own connection to ``lens.sqlite3`` (``realm_rekey_outside._rekey_lens``) calls
  :func:`bump_store_revision` in its transaction.
* The recipe shelf's documents live outside the database; the family's door
  (``realm_sync.document_family.DocumentStore``) calls :func:`bump_lens_revision` after it changes
  one, so a share, a withdrawal and a realm pull adopting a recipe all move it.
* It rides on the four ``lens.*.changed`` events and every ``runtime.lens.*`` answer: 0 new
  realtime messages, one integer on messages already sent. An older Eternia ignores the field.

A module of its own, apart from ``store.py``: the recipe shelf may move this counter and read
it, and reach nothing else of the store (``test_the_shelf_cannot_reach_the_lens_store``).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

__layer__ = "stores"

#: Seconds a shelf bump waits for the store's write lock (the poller holds it for one poll).
_BUMP_WAIT_SECONDS = 5.0


def bump_store_revision(conn: sqlite3.Connection) -> None:
    """Move the Lens store revision by one, inside ``conn``'s open transaction."""

    conn.execute("CREATE TABLE IF NOT EXISTS store_revision (id INTEGER PRIMARY KEY CHECK (id = 1), "
                 "revision INTEGER NOT NULL)")
    conn.execute("INSERT INTO store_revision (id, revision) VALUES (1, 1) "
                 "ON CONFLICT (id) DO UPDATE SET revision = revision + 1")


def read_store_revision(path: Path) -> int:
    """The committed revision of the Lens store at ``path``, read-only: 0 when there is no store
    or nothing has bumped it yet."""

    if not path.is_file():
        return 0
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)) as conn:
            row = conn.execute("SELECT revision FROM store_revision WHERE id = 1").fetchone()
    except sqlite3.Error:
        return 0
    return 0 if row is None else int(row[0])


def _default_path() -> Path:
    from .store import default_path

    return default_path()


def lens_revision() -> int:
    """The current revision of this runtime's Lens store."""

    return read_store_revision(_default_path())


def bump_lens_revision() -> None:
    """A Lens change held outside the database (a recipe shelf document) happened: move the
    revision of this runtime's store, creating the counter if the store is new."""

    path = _default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=_BUMP_WAIT_SECONDS)) as conn, conn:
        bump_store_revision(conn)
