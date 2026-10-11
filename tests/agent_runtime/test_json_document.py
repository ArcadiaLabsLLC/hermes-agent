"""D1.08 S2 — the versioned JSON document reader the two slot stores share.

Every fault reads as the EMPTY document of the current schema: a missing file, a
corrupt one, a payload that is not an object, a collection that is missing or is
not an object. A valid document round-trips unchanged.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import workspace_slot_env, workspace_slot_runs
from agent_runtime.json_document import read_versioned_document

EMPTY = {"schema_version": 3, "items": {}}


@pytest.mark.parametrize(
    "content",
    [
        None,  # missing
        "{not json",
        json.dumps(["a", "list"]),
        json.dumps({"schema_version": 3}),
        json.dumps({"schema_version": 3, "items": ["a", "list"]}),
    ],
    ids=["missing", "corrupt", "not-an-object", "no-collection", "collection-is-a-list"],
)
def test_every_fault_reads_as_the_empty_document(tmp_path, content):
    """Killing mutation: drop the collection-shape check → the
    ``collection-is-a-list`` case returns the malformed payload."""

    path = tmp_path / "doc.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    assert read_versioned_document(path, schema_version=3, collection="items") == EMPTY


def test_a_valid_document_round_trips(tmp_path):
    document = {"schema_version": 2, "items": {"a": {"x": 1}}, "extra": True}
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert read_versioned_document(path, schema_version=3, collection="items") == document


def test_the_slot_env_store_reads_a_malformed_file_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "slot_env.json"
    path.write_text(json.dumps({"schema_version": 1, "workspaces": []}), encoding="utf-8")
    monkeypatch.setattr(workspace_slot_env, "slot_env_path", lambda: path)

    assert workspace_slot_env._read() == {
        "schema_version": workspace_slot_env.SLOT_ENV_SCHEMA_VERSION,
        "workspaces": {},
    }
    assert workspace_slot_env.slot_fill("ws", "slot") is None


def test_the_runs_store_reads_a_malformed_file_as_empty_and_writes_over_it(tmp_path, monkeypatch):
    path = tmp_path / "runs.json"
    path.write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(workspace_slot_runs, "runs_path", lambda: path)

    assert workspace_slot_runs.all_runs() == []
    workspace_slot_runs.record_run({"run_id": "r1", "workspace_id": "ws"})
    assert [run["run_id"] for run in workspace_slot_runs.all_runs()] == ["r1"]
