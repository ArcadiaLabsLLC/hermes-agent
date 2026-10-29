"""S1a of the page-open write storm: a content-equal actor upsert is a no-op.

Plan: ``docs/agent-runtime-harness/planned/office-page-open-write-storm.md``
§3 and §5 (T1–T4). Autouse conftest fixtures isolate the runtime root.
"""

from __future__ import annotations

import copy
import hashlib

import pytest

from agent_runtime import paths
from agent_runtime.errors import StaleRevision
from agent_runtime.events import EventLog
from agent_runtime.office_store import OfficeStore
from agent_runtime.office_store.noop import unchanged
from agent_runtime.store import WorkspaceStore


def _workspace() -> str:
    ws = WorkspaceStore().create(name="Noop")
    WorkspaceStore().set_active(ws.id)
    return ws.id


def _payload() -> dict:
    return {
        "persona_id": "dev",
        "items": [
            {"item_id": "dev", "persona_id": "dev", "kind": "agent", "position": [1.5, 2.0], "folder": "Agents"},
            {"item_id": "desk-dev", "persona_id": "dev", "kind": "desk", "position": [1.5, 3.6], "folder": "Desks"},
        ],
    }


def _event_count() -> int:
    return sum(1 for _ in EventLog().iter_from_offset(0))


def _sha(ws: str, actor_key: str) -> str:
    return hashlib.sha256(paths.office_actor_path(ws, actor_key).read_bytes()).hexdigest()


def test_t1_an_identical_upsert_writes_nothing_and_acks_the_live_row():
    ws = _workspace()
    store = OfficeStore()
    live = store.upsert_actor(ws, _payload())
    before_sha, before_events = _sha(ws, "dev"), _event_count()

    outcome = store.upsert_actor_outcome(ws, _payload(), expect_revision=live.revision, updated_by="launcher")

    assert outcome.written is False
    assert outcome.row == live
    assert outcome.row.revision == live.revision == 1
    assert _sha(ws, "dev") == before_sha
    assert _event_count() == before_events
    # The row door answers the same live row through the same rule.
    assert store.upsert_actor(ws, _payload()) == live
    assert _event_count() == before_events


def test_t2_one_changed_field_writes_one_revision_and_two_events():
    ws = _workspace()
    store = OfficeStore()
    live = store.upsert_actor(ws, _payload())
    before_events = _event_count()
    moved = _payload()
    moved["items"][0]["position"] = [4.0, 2.0]

    outcome = store.upsert_actor_outcome(ws, moved, expect_revision=live.revision)

    assert outcome.written is True
    assert outcome.row.revision == live.revision + 1
    assert outcome.row.items[0].position != live.items[0].position
    assert _event_count() == before_events + 2  # state.patched + office.actor.upserted

    refoldered = copy.deepcopy(moved)
    refoldered["items"][1]["folder"] = "Ops"
    again = store.upsert_actor_outcome(ws, refoldered)
    assert again.written is True and again.row.revision == live.revision + 2


def test_t3_an_identical_payload_with_a_stale_token_is_still_refused():
    ws = _workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _payload())
    store.upsert_actor(ws, {**_payload(), "backing_profile": "other"})  # revision 2
    before_sha, before_events = _sha(ws, "dev"), _event_count()
    live_payload = {**_payload(), "backing_profile": "other"}

    with pytest.raises(StaleRevision):
        store.upsert_actor_outcome(ws, live_payload, expect_revision=1)

    assert _sha(ws, "dev") == before_sha
    assert _event_count() == before_events


def test_t4_a_payload_equal_to_an_archived_row_is_the_re_add_and_writes():
    ws = _workspace()
    store = OfficeStore()
    store.upsert_actor(ws, _payload())
    archived = store.remove_actor(ws, "dev", record_tombstone=False)
    assert not store.actor_exists(ws, "dev")
    before_events = _event_count()

    outcome = store.upsert_actor_outcome(ws, _payload(), resurrect=True)

    assert outcome.written is True
    assert outcome.row.state == "active"
    assert outcome.row.revision == archived.revision + 1
    assert store.actor_exists(ws, "dev")
    assert _event_count() > before_events


def test_dry_run_is_unchanged_and_says_nothing_was_written():
    ws = _workspace()
    store = OfficeStore()
    live = store.upsert_actor(ws, _payload())
    before_events = _event_count()

    outcome = store.upsert_actor_outcome(ws, _payload(), dry_run=True)

    assert outcome.written is False
    assert outcome.row.revision == live.revision + 1  # the would-be row, as before
    assert _event_count() == before_events


def test_unchanged_ignores_only_the_stamped_fields():
    ws = _workspace()
    store = OfficeStore()
    live = store.upsert_actor(ws, _payload())
    import dataclasses

    stamped = dataclasses.replace(live, revision=9, updated_by="someone", updated_at=None, created_at=None)
    assert unchanged(live, stamped)
    assert not unchanged(live, dataclasses.replace(live, backing_profile="x"))
    assert not unchanged(live, dataclasses.replace(live, state="archived"))
