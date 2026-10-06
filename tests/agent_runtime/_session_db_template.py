"""A fresh ``state.db`` per test, copied from one built by the real code (suite-speed Stage 4F).

Creating a ``SessionDB`` on a path that does not exist runs the whole schema and
FTS script, and with ``journal_mode=DELETE`` every DDL statement is an fsync:
0.8-1.0 s per database on the workstation (measured 2026-10-05), against 0.02 s
to copy the finished file and open it. A store-heavy file that opens a fresh
chat store in half its tests spends most of its wall there.

What this does: once per module, the REAL ``SessionDB`` builds a template at a
scratch path (opened twice, so the template is the steady state a store reaches
after its first writer open stamps its data-migration marker). For each test, a
WRITER open of a path that does not exist yet first receives a copy of that
template; everything after the copy — every open, pragma, migration check,
write and read — is the production code on the test's own file. A READ open of
an absent store is untouched, so "a read never creates the store" still holds.

What it does NOT prove: the fresh-file schema path itself. That is
``tests/hermes_state``'s subject, and a file whose subject it is must not use
this fixture. Each test still gets its own file; nothing is shared between
tests but the template's bytes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def _session_db_template(tmp_path_factory) -> Path:
    from hermes_state import SessionDB

    path = tmp_path_factory.mktemp("session_db_template") / "state.db"
    for _ in range(2):
        SessionDB(db_path=path).close()
    return path


@pytest.fixture
def session_db_from_template(_session_db_template, monkeypatch):
    """Seed every writer-opened, not-yet-existing ``state.db`` from the template."""
    import hermes_state

    original = hermes_state.SessionDB.__init__

    def seeded_init(self, db_path=None, read_only=False):
        target = Path(db_path) if db_path else Path(hermes_state._default_db_path())
        hermes_state._ensure_test_isolation(target)  # the production guard, before the copy writes
        if not read_only and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_session_db_template, target)
        original(self, db_path=db_path, read_only=read_only)

    monkeypatch.setattr(hermes_state.SessionDB, "__init__", seeded_init)
