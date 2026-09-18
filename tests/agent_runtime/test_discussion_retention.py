"""Retention lifecycle for native discussion runs.

Real SQLite room/run/attempt stores and the production service; only the model
boundary is deterministic (see ``test_discussion_runtime``).
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from gateway import hosted_rooms
from tests.agent_runtime.test_discussion_runtime import (  # noqa: F401 - pytest fixture
    begin,
    command,
    engine,
    settled,
    wait_until,
)

pytestmark = pytest.mark.timeout(180)


def _pins(db_path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table'"
                " AND name='hosted_room_history_pins'"
            ).fetchone()
            is None
        ):
            return set()
        return {
            str(row[0])
            for row in conn.execute("SELECT room_id FROM hosted_room_history_pins")
        }


def test_start_takes_no_retention_claim_and_end_takes_exactly_one(engine):
    service, _ctx = engine
    run = begin(service)
    wait_until(lambda: settled(service, run))

    # A live room is not a prune candidate, so a pin taken at Start protects
    # nothing and is never released — that was one leaked row per run, forever.
    assert _pins(service.db_path) == set()

    command(service, run, "end")
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "ended")

    assert _pins(service.db_path) == {run["run_id"]}
    # And the claim it took is load-bearing: End is not Delete history.
    hosted_rooms.prune_disbanded_rooms(service.db_path, now=time.time() + 365 * 86400)
    view = service.view("ws", run["run_id"])
    assert [e for e in view["log"]["events"] if e["kind"] == "message.member"]
    assert view["run"]["error"] is None


def test_end_completes_and_releases_claims_when_retention_is_full(engine, monkeypatch):
    service, _ctx = engine
    run = begin(service)
    wait_until(lambda: settled(service, run))
    monkeypatch.setattr(hosted_rooms, "MAX_RETAINED_ROOM_HISTORIES", 0)

    command(service, run, "end")
    ended = wait_until(
        lambda: (
            view
            if (view := service.view("ws", run["run_id"]))["run"]["phase"] == "ended"
            else None
        ),
        timeout=30,
    )

    # Retention is host storage policy, never lifecycle authority: the refusal is
    # surfaced, not swallowed, and it does not strand the run in `ending`.
    assert ended["run"]["error"] == "history_retention_full"
    assert _pins(service.db_path) == set()
    # Positive control: both claims really were released by that End.
    table = service.definitions.get("table", "ws", "table")
    updated = service.definitions.save_table("ws", "table", table.spec, expect_revision=table.revision)
    second = service.begin(
        "ws", "table", expect_revision=updated.revision, key="after-full", topic="Again", actor_id="operator"
    )
    assert second["run_id"] != run["run_id"]
    wait_until(lambda: settled(service, second))
