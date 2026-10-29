"""RT-SESSIONS-EXPORT-HOME-WRITES: `hermes sessions export` reads a store whose directory it cannot write.

SQLite cannot attach ``mode=ro`` to a WAL store when its ``-shm``/``-wal`` cannot be created, so the
launcher's owner-chat import of another account's home failed "attempt to write a readonly
database". ``hermes_state`` rebinds ``read_only_db_uri`` through the fork-owned
``hermes_state_ro_snapshot`` (``# fork seam``); this drives UPSTREAM'S caller — ``cmd_sessions``
→ ``SessionDB(read_only=True)`` → ``_connect_read_only`` — through the rebound builder.
"""

import json
import os
import stat
import sys
from argparse import Namespace

import pytest

from hermes_cli import sessions_cmd

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX directory permissions a non-root user cannot bypass",
)


def _export_args(**over):
    base = dict(
        sessions_action="export", session_id=None, format="jsonl", output="-", redact=False,
        dry_run=False, only=None,
    )
    base.update({name: None for name in sessions_cmd._FILTER_ARGS})
    base.update(over)
    return Namespace(**base)


@pytest.fixture
def unwritable_home(tmp_path, monkeypatch):
    import hermes_state

    home = tmp_path / "home"
    home.mkdir()
    with hermes_state.SessionDB(db_path=home / "state.db") as seed:
        seed.create_session("sess-ro-home", source="cli")
        seed.append_message("sess-ro-home", "user", "hello from a read-only home")
    for leftover in home.iterdir():  # only the checkpointed store: no -wal/-shm, no lock files
        if leftover.name != "state.db":
            if leftover.is_dir():
                continue
            leftover.unlink()
    monkeypatch.setenv("HERMES_HOME", str(home))
    home.chmod(stat.S_IRUSR | stat.S_IXUSR)
    yield home
    home.chmod(stat.S_IRWXU)


def test_export_reads_a_store_in_an_unwritable_home(unwritable_home, capsys):
    rc = sessions_cmd.cmd_sessions(_export_args(session_id="sess-ro-home"))

    out = capsys.readouterr().out
    assert rc in (None, 0), out
    record = json.loads(out.splitlines()[0])
    assert record["id"] == "sess-ro-home"
    assert "hello from a read-only home" in out
    assert sorted(p.name for p in unwritable_home.iterdir() if p.is_file()) == ["state.db"]


def test_a_writable_home_keeps_upstreams_plain_read_only_uri(tmp_path):
    import hermes_state

    db = tmp_path / "state.db"
    db.touch()
    assert not hermes_state.read_only_db_uri(db).endswith("immutable=1")


def test_a_live_wal_keeps_the_plain_uri_even_when_unwritable(tmp_path):
    import hermes_state

    db = tmp_path / "state.db"
    db.touch()
    (tmp_path / "state.db-wal").touch()
    tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert not hermes_state.read_only_db_uri(db).endswith("immutable=1")
    finally:
        tmp_path.chmod(stat.S_IRWXU)
    (tmp_path / "state.db-wal").unlink()  # positive control: the same store, only the -wal gone
    tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert hermes_state.read_only_db_uri(db).endswith("immutable=1")
    finally:
        tmp_path.chmod(stat.S_IRWXU)
