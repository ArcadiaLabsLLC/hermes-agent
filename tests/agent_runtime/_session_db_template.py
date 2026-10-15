"""A fresh ``state.db`` per test, copied from one built by the real code (suite-speed Stage 4F).

Creating a ``SessionDB`` on a path that does not exist runs the whole schema and
FTS script, and with ``journal_mode=DELETE`` every DDL statement is an fsync:
0.8-1.0 s per database on the workstation (measured 2026-10-05), against 0.02 s
to copy the finished file and open it. A store-heavy file that opens a fresh
chat store in half its tests spends most of its wall there.

What this does: the first time a test in a module WRITER-opens a path that does
not exist yet, the REAL ``SessionDB`` builds that module's template at a scratch
path (opened twice, so the template is the steady state a store reaches after
its first writer open stamps its data-migration marker). That open, and every
later one in the module, first receives a copy of the template; everything
after the copy — every open, pragma, migration check, write and read — is the
production code on the test's own file. A READ open of an absent store is
untouched, so "a read never creates the store" still holds
(``test_session_db_template.py`` pins all three arms). A module that never
opens a store never builds a template.

Scope (design sweep D3.11): autouse for every test under ``tests/agent_runtime``
(``tests/agent_runtime/conftest.py`` imports it). The template is built with
the ``SessionDB.__init__`` that stood when the test's fixtures were set up, so a
test that wraps ``__init__`` in its body counts its own opens, not the build.

What it does NOT prove: the fresh-file schema path itself. That is
``tests/hermes_state``'s subject (outside this directory), and a test here whose
subject it is opts out with ``@pytest.mark.fresh_schema_path``. Each test still
gets its own file; nothing is shared between tests but the template's bytes.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

#: Opt-out mark: the test's subject is the fresh-file schema build itself.
FRESH_SCHEMA_PATH_MARK = "fresh_schema_path"

_TEMPLATES: dict[str, Path] = {}
_TEMPLATE_LOCK = threading.Lock()


def _module_template(module: str, tmp_path_factory, build_init) -> Path:
    """The module's template, built on its first need by ``build_init``."""

    with _TEMPLATE_LOCK:
        path = _TEMPLATES.get(module)
        if path is None or not path.exists():
            from hermes_state import SessionDB

            path = tmp_path_factory.mktemp("session_db_template") / "state.db"
            for _ in range(2):
                db = SessionDB.__new__(SessionDB)
                build_init(db, db_path=path)
                db.close()
            _TEMPLATES[module] = path
        return path


@pytest.fixture(autouse=True)
def session_db_from_template(request, tmp_path_factory, monkeypatch):
    """Seed every writer-opened, not-yet-existing ``state.db`` from the module's template."""

    if request.node.get_closest_marker(FRESH_SCHEMA_PATH_MARK) is not None:
        return
    import hermes_state

    original = hermes_state.SessionDB.__init__
    module = str(request.node.path)

    def seeded_init(self, db_path=None, read_only=False):
        target = Path(db_path) if db_path else Path(hermes_state._default_db_path())
        hermes_state._ensure_test_isolation(target)  # the production guard, before the copy writes
        if not read_only and not target.exists():
            template = _module_template(module, tmp_path_factory, original)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(template, target)
        original(self, db_path=db_path, read_only=read_only)

    monkeypatch.setattr(hermes_state.SessionDB, "__init__", seeded_init)
