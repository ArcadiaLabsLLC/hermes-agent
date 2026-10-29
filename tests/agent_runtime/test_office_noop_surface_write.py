"""S1b of the page-open write storm: a content-equal surface update is a no-op.

Plan: ``docs/agent-runtime-harness/planned/office-page-open-write-storm.md``
§3 and §5 (T5–T6). Autouse conftest fixtures isolate the runtime root.
"""

from __future__ import annotations

import hashlib

import pytest

from agent_runtime import paths
from agent_runtime.errors import StaleRevision
from agent_runtime.events import EventLog
from agent_runtime.office_store import OfficeStore
from agent_runtime.store import WorkspaceStore


def _workspace() -> str:
    ws = WorkspaceStore().create(name="Noop surface")
    WorkspaceStore().set_active(ws.id)
    return ws.id


def _events() -> list:
    return [event for _, event in EventLog().iter_from_offset(0)]


def _sha(ws: str) -> str:
    return hashlib.sha256(paths.office_surface_path(ws).read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "folders",
    [["Agents", "Desks"], [], ["Desks", "Agents", "Desks"]],
    ids=["defaults", "empty", "reordered-duplicate"],
)
def test_t5_a_normalized_equal_folder_list_writes_nothing(folders):
    ws = _workspace()
    store = OfficeStore()
    live = store.ensure_surface(ws)
    before_sha, before_events = _sha(ws), len(_events())

    outcome = store.update_surface_outcome(
        ws, folders=folders, expect_revision=live.revision, updated_by="launcher"
    )

    assert outcome.written is False
    assert outcome.row == live
    assert outcome.row.revision == live.revision == 1
    assert _sha(ws) == before_sha
    assert len(_events()) == before_events
    # The row door answers the same live row through the same rule.
    assert store.update_surface(ws, folders=folders) == live


def test_t5_an_equal_list_with_a_stale_token_is_still_refused():
    ws = _workspace()
    store = OfficeStore()
    store.ensure_surface(ws)
    before_sha = _sha(ws)

    with pytest.raises(StaleRevision):
        store.update_surface_outcome(ws, folders=["Agents", "Desks"], expect_revision=0)

    assert _sha(ws) == before_sha


def test_t6_adding_a_folder_writes_one_revision_a_patch_and_a_domain_event():
    ws = _workspace()
    store = OfficeStore()
    live = store.ensure_surface(ws)
    before = len(_events())

    outcome = store.update_surface_outcome(ws, folders=["Ops"], expect_revision=live.revision)

    assert outcome.written is True
    assert outcome.row.revision == live.revision + 1
    assert outcome.row.folders == ["Agents", "Desks", "Ops"]
    types = [event.type for event in _events()[before:]]
    assert "office.surface.updated" in types
    assert "state.patched" in types
    # …and repeating that write is now the no-op.
    again = store.update_surface_outcome(ws, folders=["Ops", "Agents"])
    assert again.written is False
    assert again.row == outcome.row


def test_a_dry_run_reports_unwritten_with_the_would_be_row():
    ws = _workspace()
    store = OfficeStore()
    live = store.ensure_surface(ws)
    before_sha = _sha(ws)

    outcome = store.update_surface_outcome(ws, folders=["Ops"], dry_run=True)

    assert outcome.written is False
    assert outcome.row.revision == live.revision + 1
    assert _sha(ws) == before_sha
