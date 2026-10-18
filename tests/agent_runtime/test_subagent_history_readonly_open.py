"""The native history read survives a writer's exit window (FORK-TEST-OWNED-CHILD-READS).

A ``mode=ro`` open of a WAL store right after its writer exits can answer SQLITE_READONLY
("attempt to write a readonly database") because the -shm recovery needs a writer; the
history read retries that one error, bounded, with controlled time.
"""

import sqlite3

import pytest

from agent_runtime.conversations import subagent_history


class _FlakyDB:
    def __init__(self, failures, message="attempt to write a readonly database"):
        self.failures, self.message, self.opens = failures, message, 0

    def __call__(self, *, db_path, read_only):
        assert read_only is True
        self.opens += 1
        if self.opens <= self.failures:
            raise sqlite3.OperationalError(self.message)
        return ("db", db_path)


@pytest.fixture
def flaky(monkeypatch):
    def install(failures, **kw):
        fake = _FlakyDB(failures, **kw)
        import hermes_state

        monkeypatch.setattr(hermes_state, "SessionDB", fake)
        return fake

    return install


def test_the_recovery_window_is_retried_until_the_store_opens(flaky):
    fake, naps = flaky(2), []
    assert subagent_history._open_history_db("state.db", sleep=naps.append) == ("db", "state.db")
    assert fake.opens == 3 and naps == [subagent_history._READONLY_RECOVERY_BACKOFF_S] * 2


def test_the_retry_is_bounded(flaky):
    fake, naps = flaky(99), []
    with pytest.raises(sqlite3.OperationalError, match="readonly database"):
        subagent_history._open_history_db("state.db", sleep=naps.append)
    assert fake.opens == subagent_history._READONLY_RECOVERY_ATTEMPTS + 1
    assert len(naps) == subagent_history._READONLY_RECOVERY_ATTEMPTS


def test_any_other_open_failure_is_not_retried(flaky):
    fake, naps = flaky(1, message="database is locked"), []
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        subagent_history._open_history_db("state.db", sleep=naps.append)
    assert fake.opens == 1 and naps == []
