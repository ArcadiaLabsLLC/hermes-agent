"""``PersonaAssignmentStore`` — the READ/CLOSE side of the persona-assignment
store — and the retired-assignment task-id migration.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.models import Event, PersonaAssignment
from agent_runtime.serde import from_jsonable, to_jsonable
from agent_runtime.persona_assignments.scan import PersonaAssignmentScan
from agent_runtime.persona_assignments.tokens import (
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
)
from agent_runtime.persona_assignments.vocabulary import (
    ACTIVE_ASSIGNMENT_STATES,
    TERMINAL_ASSIGNMENT_STATES,
)

__layer__ = "stores"

__all__ = [
    "migrate_retired_persona_assignment_task_ids",
    "PersonaAssignmentStore",
]


class PersonaAssignmentStore:
    """READ/CLOSE side of the persona-assignment store.

    S70 removed the MINT side (``create`` / ``create_or_resume`` / the
    ``PersonaAssignmentSpec`` request shape and the ``assignment_evidence_kind``
    / ``assignment_archive_scope`` / ``assignment_signal_hash`` /
    ``assignment_signal_hash_from_parts`` derivations). The only production
    minter was the free-floating queue verb chain (``persona instance create``'s
    display-name-less branch and ``persona instance message``), whose queued
    rows had no consumer since the 2026-07-30 chat-only purge removed ticking.

    AX2 (2026-08-31) took the READ side's two remaining consumers with it: the
    launcher deleted every read of the ``persona_assignments`` wire block
    (launcher ``6bf48ba26``) and hermes stopped projecting it, and the two
    retire guards that keyed on an active assignment are gone with their
    argument. What is deliberately KEPT is the OPERATOR's settle path: residual
    rows exist on live runtime roots, and ``harness persona assignments``,
    ``persona instance close``/``archive`` and the chat-delete unbind are the
    only ways to see and terminate them through :meth:`complete`. Retiring those
    too would strand residue with no verb that can reach it — the same reason
    the launcher's installer keeps its ``persona_assignments`` preserved-path
    rows. Read paths retire; stored bytes do not."""

    def __init__(self, event_log: EventLog | None = None):
        self.event_log = event_log or EventLog()

    def get(self, assignment_id: str) -> PersonaAssignment:
        raw = json.loads(paths.persona_assignment_path(assignment_id).read_text(encoding="utf-8"))
        return from_jsonable(PersonaAssignment, raw)

    def update(self, assignment: PersonaAssignment) -> PersonaAssignment:
        assignment.updated_at = now()
        self._write(assignment)
        return self.get(assignment.id)

    def scan_all(self) -> PersonaAssignmentScan:
        """Every assignment this root HAS, plus how many rows did not decode.

        THE chokepoint, the assignment twin of
        :meth:`PersonaInstanceStore.scan_all`. ``list_all`` is the thin list
        view over it, and since AX2 it is the only view anything asks for: the
        retire guard that consumed the ``unreadable`` count as a write fence is
        gone. The count still travels rather than being folded away, because a
        settle verb that showed the operator a SHORT list as if it were the
        whole store is the same silent-skip defect one layer up.
        """

        directory = paths.persona_assignments_dir()
        if not directory.exists():
            return PersonaAssignmentScan([], 0)
        assignments: list[PersonaAssignment] = []
        unreadable = 0
        for path in sorted(directory.glob("*.json")):
            try:
                assignments.append(from_jsonable(PersonaAssignment, json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                unreadable += 1
                continue
        return PersonaAssignmentScan(sorted(assignments, key=lambda item: item.created_at), unreadable)

    def list_all(self) -> list[PersonaAssignment]:
        return self.scan_all().assignments

    def list_for_persona(self, persona_id: str) -> list[PersonaAssignment]:
        normalized = safe_assignment_token(persona_id)
        return [assignment for assignment in self.list_all() if assignment.persona_id == normalized]

    def find_active(self, *, persona_id: str | None = None, goal_id: str | None = None, stage_id: str | None = None, kind: str | None = None) -> list[PersonaAssignment]:
        wanted_persona = safe_assignment_token(persona_id) if persona_id else None
        wanted_goal = safe_optional_token(goal_id) if goal_id else None
        wanted_stage = safe_optional_token(stage_id) if stage_id else None
        wanted_kind = safe_assignment_token(kind) if kind else None
        return [
            assignment
            for assignment in self.list_all()
            if assignment.state in ACTIVE_ASSIGNMENT_STATES
            and (wanted_persona is None or assignment.persona_id == wanted_persona)
            and (wanted_goal is None or assignment.goal_id == wanted_goal)
            and (wanted_stage is None or assignment.stage_id == wanted_stage)
            and (wanted_kind is None or assignment.kind == wanted_kind)
        ]

    def complete(self, assignment_id: str, *, state: str = "completed", error: str | None = None) -> PersonaAssignment:
        assignment = self.get(assignment_id)
        target_state = state if state in TERMINAL_ASSIGNMENT_STATES else "completed"
        target_error = safe_assignment_text(error or "", limit=500) or None
        if assignment.state in TERMINAL_ASSIGNMENT_STATES and assignment.state == target_state and assignment.last_error == target_error:
            return assignment
        assignment.state = target_state
        assignment.last_error = target_error
        assignment.completed_at = now()
        updated = self.update(assignment)
        self._event("persona_assignment.closed", updated, {"state": updated.state})
        return updated

    def _write(self, assignment: PersonaAssignment) -> None:
        path = paths.persona_assignment_path(assignment.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, to_jsonable(assignment), indent=2, sort_keys=True)

    def _event(self, event_type: str, assignment: PersonaAssignment, payload: dict[str, Any]) -> None:
        self.event_log.append(
            Event(
                ts=now(),
                type=event_type,
                task_id=assignment.task_id,
                run_id=assignment.run_ids[-1] if assignment.run_ids else None,
                persona_id=assignment.persona_id,
                payload={
                    **payload,
                    "assignment_id": assignment.id,
                    "persona_instance_id": assignment.persona_instance_id,
                    "kind": assignment.kind,
                    "client_message_id": assignment.client_message_id,
                    "title": assignment.title,
                    "message": assignment.message,
                    "stage_id": assignment.stage_id,
                    "goal_id": assignment.goal_id,
                    "repo": assignment.repo,
                    "affected_paths": list(assignment.affected_paths or []),
                    "proof_targets": list(assignment.proof_targets or []),
                    "acceptance": list(assignment.acceptance or []),
                    "non_goals": list(assignment.non_goals or []),
                    "allowed_decisions": list(assignment.allowed_decisions or []),
                },
            )
        )


def migrate_retired_persona_assignment_task_ids(*, dry_run: bool) -> dict[str, Any]:
    """Archive pre-retirement mission-lane assignment rows.

    A non-null raw ``task_id`` is the migration discriminator. Rows move out of
    the live store intact; no record is rewritten or deleted. Repeating the
    apply is inert because migrated rows are no longer present in the live
    directory.
    """

    live_dir = paths.persona_assignments_dir()
    archive_dir = paths.persona_assignments_archive_dir() / "retired_task_id"
    sources = sorted(live_dir.glob("*.json")) if live_dir.exists() else []
    eligible: list[tuple[Path, str]] = []
    held: list[dict[str, str]] = []
    for source in sources:
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc:
            held.append({"path": source.name, "reason": f"unreadable:{type(exc).__name__}"})
            continue
        if not isinstance(raw, dict) or raw.get("task_id") is None:
            continue
        assignment_id = safe_assignment_token(raw.get("id")) or source.stem
        eligible.append((source, assignment_id))

    archived = 0
    if not dry_run and eligible:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for source, assignment_id in eligible:
            target = archive_dir / source.name
            if target.exists():
                held.append({"assignment_id": assignment_id, "reason": "archive_target_exists"})
                continue
            shutil.move(str(source), str(target))
            archived += 1

    return {
        "ok": not held,
        "migration": "retired_persona_assignment_task_id",
        "dry_run": bool(dry_run),
        "scanned": len(sources),
        "eligible": len(eligible),
        "archived": archived,
        "assignment_ids": [assignment_id for _, assignment_id in eligible],
        "archive_dir": str(archive_dir),
        "held": held,
    }
