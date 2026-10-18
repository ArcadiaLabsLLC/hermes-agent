"""The autouse SessionDB template's contract (D3.11, h1-setup).

``tests/_downstream/session_db_template.py`` is autouse for every test (the chain registers
it): a WRITER open of an absent store is seeded from a stripped template and is then the
fresh store the production code would have built (same schema, pragmas, ``state_meta``
keys and sidecars; its own identity); a READ open of an absent store is untouched; a test
marked ``fresh_schema_path`` gets the production open alone.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

import hermes_state  # imported at collection, so the chain finds it at setup

_PRAGMAS = ("user_version", "auto_vacuum", "page_size", "journal_mode", "freelist_count", "page_count", "encoding")


def _shape(path):
    conn = sqlite3.connect(str(path))
    try:
        return {
            "master": sorted(conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall(), key=repr),
            "pragmas": {name: conn.execute(f"PRAGMA {name}").fetchone()[0] for name in _PRAGMAS},
            "schema_version": conn.execute("SELECT * FROM schema_version").fetchall(),
            "meta_keys": sorted(row[0] for row in conn.execute("SELECT key FROM state_meta")),
            "meta": dict(conn.execute("SELECT key, value FROM state_meta").fetchall()),
            "application_id": conn.execute("PRAGMA application_id").fetchone()[0],
        }
    finally:
        conn.close()


def _sidecars(path):
    return sorted(p.name[len(path.name):] for p in path.parent.iterdir() if p.name.startswith(path.name))


def _fresh(path):
    """A store built by the production open alone, as an opted-out test gets it."""
    import hermes_state

    from tests._downstream import session_db_template as template

    template._BUILDING.active = True
    try:
        hermes_state.SessionDB(db_path=path).close()
    finally:
        template._BUILDING.active = False


def test_a_seeded_store_is_the_fresh_store_with_its_own_identity(tmp_path):
    """Mutation: drop ``_strip``'s ``DELETE FROM state_meta`` (every seeded store then shares the
    template's ``store_instance_id`` and file generation)."""
    import hermes_state

    fresh = tmp_path / "fresh" / "state.db"
    fresh.parent.mkdir()
    _fresh(fresh)
    seeded = [tmp_path / f"seeded{i}" / "state.db" for i in range(2)]
    for path in seeded:
        hermes_state.SessionDB(db_path=path).close()

    want = _shape(fresh)
    for path in seeded:
        got = _shape(path)
        for part in ("master", "pragmas", "schema_version", "meta_keys"):
            assert got[part] == want[part], part
        assert got["application_id"] != 0
        assert _sidecars(path) == _sidecars(fresh)
    first, second = (_shape(path) for path in seeded)
    for key in ("store_instance_id", "store_created_at_utc", "db_file_generation"):
        assert first["meta"][key] != second["meta"][key], key
    assert first["application_id"] != second["application_id"]


def test_the_chains_per_test_wrappers_do_not_split_the_template(monkeypatch, tmp_path_factory):
    """The fsync wrapper is re-made for every test, and the sandbox paths (home, lock dir) move
    with every test; a key that saw them would build a template per test (measured: 245 builds
    for 245 tests in ``test_hermes_state.py``). Mutations: drop the ``CHAIN_WRAPPER_ATTR`` filter
    in ``_attr_ids``; make ``_token`` return ``id(value)`` first."""
    import sys

    import hermes_state

    from tests._downstream import session_db_template as template
    from tests._downstream import state_db_no_fsync

    if sys.platform == "darwin":
        pytest.skip("macOS keeps synchronous=FULL: no per-test wrapper there")
    sandbox = os.path.normcase(str(tmp_path_factory.getbasetemp()))
    before = template.template_key(sandbox)
    current = hermes_state._connect_tracked_db
    monkeypatch.setattr(hermes_state, "_connect_tracked_db", state_db_no_fsync._no_fsync(current.__wrapped__))
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", tmp_path_factory.mktemp("other_home") / "state.db")
    monkeypatch.setenv("HERMES_GATEWAY_LOCK_DIR", str(tmp_path_factory.mktemp("other_locks")))
    roots = hermes_state._STATE_DB_GUARD_EXTRA_DENY_ROOTS
    monkeypatch.setattr(hermes_state, "_STATE_DB_GUARD_EXTRA_DENY_ROOTS", tuple(root for root in roots))
    assert template.template_key(sandbox) == before


def test_a_patched_state_module_gets_its_own_template(tmp_path, monkeypatch):
    """Mutation: drop the ``hermes_state*`` module identities from ``template_key``."""
    import hermes_state
    import hermes_state_schema

    from tests._downstream import session_db_template as template

    hermes_state.SessionDB(db_path=tmp_path / "a" / "state.db").close()
    before = template.BUILDS["count"]
    # A new code object for a name the merged tag has (the retirement scan judges patch targets
    # against it); same behaviour, new identity — the patch the key must see.
    holder = hermes_state_schema._holder_cmdline
    monkeypatch.setattr(hermes_state_schema, "_holder_cmdline", lambda pid: holder(pid))
    hermes_state.SessionDB(db_path=tmp_path / "b" / "state.db").close()
    assert template.BUILDS["count"] == before + 1


def test_a_read_open_of_an_absent_store_creates_nothing(tmp_path):
    import hermes_state

    path = tmp_path / "absent" / "state.db"
    with pytest.raises(Exception):
        hermes_state.SessionDB(db_path=path, read_only=True)

    assert not path.exists(), "a READ created the store"


def test_the_fixture_is_on_for_an_unmarked_test():
    import hermes_state

    assert hermes_state.SessionDB._open_writer.__name__ == "seeded_open_writer"


@pytest.mark.fresh_schema_path
def test_a_fresh_schema_path_test_gets_the_production_open():
    import hermes_state

    assert hermes_state.SessionDB._open_writer.__name__ != "seeded_open_writer"
