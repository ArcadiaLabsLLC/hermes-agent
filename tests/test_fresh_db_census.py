"""The fresh-SessionDB census counts writer opens of an absent store, per file (D3.11).

A child pytest runs a two-test file with the census plugin loaded by name and
its own empty ini, so neither the repo's conftests nor this session's receipt
are involved: one test writer-opens a store that does not exist, the other
read-opens one (a read never creates the store, so it is never a fresh build).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

from tests._downstream import fresh_db_census

_REPO = Path(__file__).resolve().parents[1]

_TWO_TESTS = '''
from hermes_state import SessionDB


def test_fresh_writer_open(tmp_path):
    db = SessionDB(db_path=tmp_path / "fresh.db")
    # The census must not stand between SessionDB and the opener it names.
    assert db._creation_site.endswith(".test_fresh_writer_open:" + db._creation_site.rsplit(":", 1)[1])
    db.close()


def test_read_only_open_of_an_absent_store(tmp_path):
    try:
        SessionDB(db_path=tmp_path / "absent.db", read_only=True).close()
    except Exception:
        pass
'''


def test_enabled_reads_the_variable():
    assert fresh_db_census.enabled({fresh_db_census.ENV: "1"})
    assert not fresh_db_census.enabled({fresh_db_census.ENV: "0"})
    assert not fresh_db_census.enabled({})


def _half_imported_state(initializing: bool) -> types.ModuleType:
    module = types.ModuleType("hermes_state")
    module.__spec__ = ModuleSpec("hermes_state", None)
    module.__spec__._initializing = initializing
    return module


def test_a_hermes_state_another_thread_is_still_importing_is_skipped_not_a_crash(monkeypatch):
    """FORK-FRESH-DB-CENSUS-INTERNALERROR: a serve thread importing ``hermes_state`` puts it in
    ``sys.modules`` before ``SessionDB`` is bound; the census waits for the next test, the session
    lives. Killing mutation: drop the ``_initializing`` check in ``install`` — the first call raises
    AttributeError (pytest INTERNALERROR, 152 in the land-w5 gate log)."""

    monkeypatch.setattr(fresh_db_census, "_installed", {})
    monkeypatch.setitem(sys.modules, "hermes_state", _half_imported_state(True))
    assert fresh_db_census.install() is False and fresh_db_census._installed == {}
    # Finished importing and still no SessionDB: a real break, never swallowed.
    monkeypatch.setitem(sys.modules, "hermes_state", _half_imported_state(False))
    with pytest.raises(AttributeError):
        fresh_db_census.install()


@pytest.mark.timeout(120)
def test_a_child_session_counts_the_writer_open_and_not_the_read(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_two.py").write_text(_TWO_TESTS, encoding="utf-8")
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join([str(_REPO), os.environ.get("PYTHONPATH", "")]),
        HERMES_HOME=str(tmp_path / "home"),
    )
    done = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "tests._downstream.fresh_db_census",
            "-c", str(tmp_path / "pytest.ini"), "--rootdir", str(tmp_path),
            str(tmp_path / "test_two.py"),
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=110,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    receipt = tmp_path / fresh_db_census.RECEIPT
    rows = [json.loads(line) for line in receipt.read_text(encoding="utf-8").splitlines()]
    assert [row["file"] for row in rows] == ["test_two.py"]
    assert rows[0]["fresh_dbs"] == 1
    assert rows[0]["fresh_seconds"] > 0
    assert rows[0]["seconds"] >= rows[0]["fresh_seconds"]
