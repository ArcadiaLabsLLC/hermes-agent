"""A fresh ``state.db`` per test, seeded from one the real code built (suite speed; D3.11, h1-setup).

A ``SessionDB`` writer-opened on a path that does not exist runs the whole schema and FTS
script: about a hundred autocommitted statements, and with the test venv's
``journal_mode=DELETE`` each is a rollback-journal create and delete. Measured 2026-10-18
(CPU, ``synchronous=OFF``): 87-110 ms per fresh store against 24 ms for a seeded one; 100
autocommitted DDL statements cost 105 ms of CPU, the same 100 in one transaction 6 ms. Under
the bundled gate's load that was the bulk of the 2026-10-17 features run's setup
(``test_hermes_state.py`` 234 s setup, ``test_session_api.py`` 216 s).

What this does: the first time a WRITER open meets a path that does not exist, the REAL
``SessionDB`` builds a template once (one open, as a fresh store gets) and the template is
STRIPPED of everything a fresh open mints: ``schema_version`` emptied, ``state_meta`` emptied,
``application_id`` zeroed. Every such open then receives the template's bytes, and the
production ``_open_writer`` that follows takes the fresh-store branch itself: it inserts the
schema version and mints the store's own ``store_instance_id``, ``store_created_at_utc``,
backfill marker, file generation and ``application_id``. The seeded store is the fresh
store: same ``sqlite_master``, same pragmas, same ``state_meta`` keys, same sidecar files,
its own identity (``test_session_db_template.py`` pins the comparison against a store the
production code built from nothing). A READ open of an absent store is untouched.

Exactness, per open (not per module): the template is keyed by what can change a fresh
build: the identity of every attribute of every loaded ``hermes_state*`` module and of
``SessionDB`` (a monkeypatch of any of them is a new key, so a template is never built under
one test's patch and handed to another), the home's ``config.yaml`` bytes (journal mode and
the ``database:`` pragmas live there) and the ``HERMES_*`` environment bar the per-test home.
The chain's own per-test wrappers carry ``_hermes_chain_wrapper`` and are left out of the key.

What it does NOT prove: the fresh-file open itself (the quarantine-lock arm, the admitted
startup FTS rebuild). A test whose subject that is opts out with ``@pytest.mark.fresh_schema_path``;
an upstream file, which cannot carry the mark, is named in :data:`FRESH_SCHEMA_FILES`.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import types
from pathlib import Path

import pytest

#: Opt-out mark: the test's subject is the fresh-file open itself.
FRESH_SCHEMA_PATH_MARK = "fresh_schema_path"

#: Upstream files whose subject is the fresh-file open (they cannot carry the mark). A file
#: lands here when it reds with seeding on and the red is about the fresh open; say which.
FRESH_SCHEMA_FILES = frozenset(
    {
        # asserts the fresh open's FTS bootstrap marks the store stale when admission is refused
        "tests/hermes_state/test_fts_fresh_bootstrap_admission.py",
    }
)

#: Marks a chain wrapper that is re-created per test and must not split the template key.
CHAIN_WRAPPER_ATTR = "_hermes_chain_wrapper"

_TEMPLATES: dict[tuple, tuple[bytes, tuple[str, ...]]] = {}
_LOCK = threading.Lock()
_BUILDING = threading.local()
#: Templates built in this process (the guard tests read it).
BUILDS = {"count": 0}


_BY_IDENTITY = frozenset({types.FunctionType, types.BuiltinFunctionType, types.ModuleType, type, types.MethodType})
_BY_VALUE = frozenset({int, float, bool, bytes, type(None)})


def _token(value, sandbox: str | None):
    """How one attribute enters the key: code by identity (a monkeypatch is a new object),
    immutable values by equality (a fixture re-making an equal tuple is not a patch), and a
    path under the session's base temp as one token (where a test's sandbox lies never changes
    what a fresh build writes into the file)."""

    kind = type(value)
    if kind in _BY_IDENTITY:
        return id(value)
    if kind in _BY_VALUE:
        return value
    if kind is str or isinstance(value, os.PathLike):
        text = os.fspath(value)
        if sandbox is not None and isinstance(text, str) and os.path.normcase(text).startswith(sandbox):
            return "<sandbox>"
        return ("=", text)
    if kind in (tuple, frozenset) and len(value) < 16:
        return (kind.__name__, tuple(_token(item, sandbox) for item in value))
    return id(value)


def _attr_ids(namespace, sandbox: str | None = None) -> tuple:
    return tuple(
        (name, _token(value, sandbox))
        for name, value in namespace.items()
        if not (type(value) is types.FunctionType and getattr(value, CHAIN_WRAPPER_ATTR, False))
    )


def template_key(sandbox: str | None = None) -> tuple:
    """What a fresh build depends on, cheaply: code identity, the home's config, the env.

    *sandbox* is the session's pytest base temp (normcased): values under it are the test's
    isolation paths and read as one token.
    """

    modules = tuple(
        (name, _attr_ids(vars(module), sandbox))
        for name, module in sorted(sys.modules.copy().items())
        if name.startswith("hermes_state") and module is not None
    )
    session_db = sys.modules["hermes_state"].SessionDB
    try:
        from hermes_constants import get_hermes_home

        config = (get_hermes_home() / "config.yaml").read_bytes()
    except OSError:
        config = None
    env = tuple(
        sorted(
            (k, _token(v, sandbox))
            for k, v in os.environ.items()
            if k.startswith("HERMES_") and k != "HERMES_HOME"
        )
    )
    return (hash(modules), _attr_ids(vars(session_db), sandbox), config, env)


def _strip_fresh_open_marks(path: Path) -> None:
    """Undo what a fresh open mints, so the next open of a copy mints its own."""

    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM schema_version")
        conn.execute("DELETE FROM state_meta")
        conn.execute("COMMIT")
        conn.execute("PRAGMA application_id=0")
    finally:
        conn.close()


def _build_template(tmp_path_factory, init) -> tuple[bytes, tuple[str, ...]]:
    from hermes_state import SessionDB

    path = tmp_path_factory.mktemp("session_db_template") / "state.db"
    _BUILDING.active = True
    try:
        db = SessionDB.__new__(SessionDB)
        init(db, db_path=path)
        db.close()
    finally:
        _BUILDING.active = False
    _strip_fresh_open_marks(path)
    sidecars = tuple(
        p.name[len(path.name):] for p in path.parent.iterdir() if p.name.startswith(path.name + ".") and p.name.endswith(".lock")
    )
    BUILDS["count"] += 1
    return path.read_bytes(), sidecars


def _seed(target: Path, tmp_path_factory, init) -> None:
    import hermes_state

    key = template_key(os.path.normcase(str(tmp_path_factory.getbasetemp())))
    with _LOCK:
        template = _TEMPLATES.get(key)
        if template is None:
            template = _TEMPLATES[key] = _build_template(tmp_path_factory, init)
    data, sidecars = template
    hermes_state.mkdir_under_hermes_home(target.parent)  # what _open_writer does first, idempotent
    with open(target, "xb") as handle:  # never over a store that appeared meanwhile
        try:
            handle.write(data)
        except BaseException:
            handle.close()
            target.unlink()
            raise
    for suffix in sidecars:
        sidecar = target.with_name(target.name + suffix)
        if not sidecar.exists():
            sidecar.touch()


@pytest.fixture(autouse=True)
def session_db_from_template(request, tmp_path_factory, monkeypatch):
    """Seed every writer-opened, not-yet-existing ``state.db`` from the stripped template."""

    if request.node.get_closest_marker(FRESH_SCHEMA_PATH_MARK) is not None:
        return
    rel = Path(str(request.node.path)).resolve()
    try:
        rel = rel.relative_to(Path(str(request.config.rootpath)).resolve()).as_posix()
    except ValueError:
        rel = rel.as_posix()
    if rel in FRESH_SCHEMA_FILES:
        return
    hermes_state = sys.modules.get("hermes_state")
    if hermes_state is None:  # never import it for a test: import order is some tests' subject
        return
    session_db = hermes_state.SessionDB
    original = session_db._open_writer
    init = session_db.__init__

    def seeded_open_writer(self, *args, **kwargs):
        if not getattr(_BUILDING, "active", False):
            target = Path(self.db_path)
            if not target.exists():
                try:
                    _seed(target, tmp_path_factory, init)
                except Exception:  # the seed never decides an open: the fresh path runs instead
                    pass
        return original(self, *args, **kwargs)

    setattr(seeded_open_writer, CHAIN_WRAPPER_ATTR, True)
    monkeypatch.setattr(session_db, "_open_writer", seeded_open_writer)
