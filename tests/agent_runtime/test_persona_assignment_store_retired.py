"""RT-FULL-PERSONAASSIGNMENTSTORE: the assignment store is retired; its residual rows are archived, never lost."""

from __future__ import annotations

import json

from agent_runtime import paths
from agent_runtime.persona_assignments import retire_persona_assignment_store
from agent_runtime.persona_assignments.assignments import REPORT_NAME


def _row(assignment_id: str, state: str) -> dict:
    return {"id": assignment_id, "persona_id": "qa", "persona_instance_id": "personainst_qa", "state": state}


def test_residual_rows_move_byte_for_byte_into_the_archive_with_a_report(isolate_agent_runtime_root):
    live = paths.persona_assignments_dir()
    live.mkdir(parents=True)
    (live / "assign_a.json").write_text(json.dumps(_row("assign_a", "queued")), encoding="utf-8")
    (live / "assign_b.json").write_text("{not json", encoding="utf-8")  # an unreadable row still moves

    report = retire_persona_assignment_store()

    archive = paths.persona_assignments_archive_dir() / "retired_store"
    assert not live.exists()
    assert json.loads((archive / "assign_a.json").read_text(encoding="utf-8"))["state"] == "queued"
    assert (archive / "assign_b.json").read_text(encoding="utf-8") == "{not json"
    assert [(row["file"], row["state"]) for row in report["archived"]] == [
        ("assign_a.json", "queued"), ("assign_b.json", None)]
    assert report["held"] == []
    marker = json.loads((paths.store_root() / "migrations" / REPORT_NAME).read_text(encoding="utf-8"))
    assert marker["runs"][-1]["archived"] == report["archived"]
    assert retire_persona_assignment_store() is None  # idempotent: no live directory, nothing to do


def test_a_row_whose_archive_name_is_taken_is_held_in_place(isolate_agent_runtime_root):
    live = paths.persona_assignments_dir()
    live.mkdir(parents=True)
    (live / "assign_a.json").write_text(json.dumps(_row("assign_a", "completed")), encoding="utf-8")
    archive = paths.persona_assignments_archive_dir() / "retired_store"
    archive.mkdir(parents=True)
    (archive / "assign_a.json").write_text("earlier", encoding="utf-8")

    report = retire_persona_assignment_store()

    assert report["held"] == [{"file": "assign_a.json", "reason": "archive_target_exists"}]
    assert (live / "assign_a.json").exists() and (archive / "assign_a.json").read_text(encoding="utf-8") == "earlier"


def test_the_retired_verbs_are_gone_from_the_cli():
    from hermes_cli.harness_parts.persona import inspect_commands, instance_commands

    for module, name in ((inspect_commands, "_cmd_persona_assignments"),
                         (inspect_commands, "_cmd_persona_assignment_task_id_migration"),
                         (instance_commands, "_cmd_persona_instance_close"),
                         (instance_commands, "_cmd_persona_instance_archive")):
        assert not hasattr(module, name), name
    assert hasattr(instance_commands, "_cmd_persona_instance_retire")  # positive control
