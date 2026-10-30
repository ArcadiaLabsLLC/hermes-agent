"""Runtime-owned character commands over the existing agent stores.

No placement, profile view or renderer owns a second assignment ledger.
"""

from __future__ import annotations

from typing import Any

from hermes_time import now

from .character_assignment import CharacterAssignmentChange, CharacterAssignmentReason, CharacterAssignmentRefused, validate_character_record
from .character_assignment_legacy import character_legacy_sources, character_migration_choice, character_source_fingerprint
from .config.roster import ensure_persisted_personas
from .locks import character_legacy_assignment_lock
from .persona_assignments.store import PersonaInstanceStore
from .store import AgentStore

__layer__ = "stores"


def _character_subject(params: dict[str, Any]):
    kind, record_id, persona_id = params.get("kind"), params.get("id"), params.get("persona_id")
    if not isinstance(kind, str) or kind not in {"instance", "persona"} or not isinstance(record_id, str) or not record_id.strip():
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "An exact agent subject is required.")
    if kind == "instance":
        record = PersonaInstanceStore().get(record_id)
        if record.id != record_id or record.persona_id != persona_id:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Instance and persona identity must match the stored record.")
    else:
        record = next((p for p in ensure_persisted_personas() if p.id == record_id), None)
        if record is None or persona_id != record.id:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "The persona record is unavailable.")
    return record


def read_character_assignment(params: dict[str, Any]) -> dict[str, Any]:
    record = _character_subject(params)
    assignment = validate_character_record(record.character_assignment, persona=params["kind"] == "persona")
    return {"kind": params["kind"], "id": record.id, "persona_id": params["persona_id"], "assignment": assignment,
            "revision": assignment["revision"] if assignment else 0}


def preview_character_migration(params: dict[str, Any]) -> dict[str, Any]:
    record = _character_subject(params)
    instance_id = record.id if params["kind"] == "instance" else None
    with character_legacy_assignment_lock(instance_id, params["persona_id"]):
        sources = character_legacy_sources(instance_id=instance_id, persona_id=params["persona_id"], local_sources=params.get("local_sources", []))
        result = read_character_assignment(params)
        return {**result, "sources": sources, "source_fingerprint": character_source_fingerprint(sources)}


def write_character_assignment(params: dict[str, Any], *, migrate: bool = False) -> dict[str, Any]:
    record = _character_subject(params)
    instance_id = record.id if params["kind"] == "instance" else None
    with character_legacy_assignment_lock(instance_id, params["persona_id"]):
        current = read_character_assignment(params)
        receipt = None
        mode, asset = params.get("mode"), params.get("asset_reference")
        if current["assignment"] is None:
            sources = character_legacy_sources(instance_id=instance_id, persona_id=params["persona_id"], local_sources=params.get("local_sources", []))
            fingerprint = character_source_fingerprint(sources)
            if params.get("source_fingerprint") != fingerprint:
                raise CharacterAssignmentRefused(CharacterAssignmentReason.STALE, "Review the current migration inventory before activating record ownership.")
            receipt = {"version": 1, "sources": sources, "source_fingerprint": fingerprint, "migrated_at": now().isoformat()}
            if migrate:
                mode, asset = character_migration_choice(sources, persona=instance_id is None)
        elif migrate:
            # Migration retries never replay a legacy choice over a later edit.
            return current
        change = CharacterAssignmentChange(params.get("expected_revision"), mode, asset, params.get("operation_id"), receipt)
        if instance_id is not None:
            saved = PersonaInstanceStore().set_character_assignment(instance_id, change)
        else:
            saved = AgentStore().save(record, character_change=change)
        assignment = saved.character_assignment
        return {"kind": params["kind"], "id": saved.id, "persona_id": params["persona_id"], "assignment": assignment, "revision": assignment["revision"]}
