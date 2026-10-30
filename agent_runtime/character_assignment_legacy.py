"""Read-only migration inputs and the old office-writer fence.

Existing placement bytes are retained as history, never dual-written after
record activation. The character migration lock covers inventory and cutover.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .character_assignment import CharacterAssignmentReason, CharacterAssignmentRefused, validate_character_choice

__layer__ = "stores"


def character_legacy_sources(*, instance_id: str | None, persona_id: str, local_sources: Any) -> list[dict[str, Any]]:
    if not isinstance(local_sources, list) or len(local_sources) > 2048:
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "A bounded local source inventory is required.")
    sources: list[dict[str, Any]] = []
    for source in local_sources:
        if (not isinstance(source, dict) or set(source) != {"scope", "value"}
                or not isinstance(source["scope"], str) or not source["scope"] or len(source["scope"]) > 512):
            raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Invalid local migration source.")
        if not isinstance(source["value"], str) or len(source["value"]) > 512:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Invalid local migration value.")
        sources.append({"source": "client_legacy", **source})
    sources.extend(source for source in office_character_migration_sources()
                   if source["persona_id"] == persona_id and source["instance_id"] == instance_id)
    return sorted(sources, key=lambda row: json.dumps(row, sort_keys=True))


def office_character_migration_sources() -> list[dict[str, Any]]:
    """One complete scan, reusable by the batch without quadratic disk reads."""
    from .office_store import OfficeStore

    sources: list[dict[str, Any]] = []
    office = OfficeStore()
    for workspace_id in office.list_workspaces():
        scan = office.scan_actors(workspace_id)
        if scan.unreadable:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.CONFLICT, "An office inventory is unreadable; migration did not run.")
        for actor in scan.actors:
            for item in actor.items:
                if item.kind != "agent":
                    continue
                sources.append({"source": "office", "workspace_id": workspace_id, "actor_key": actor.actor_key,
                                "instance_id": actor.persona_instance_id, "persona_id": actor.persona_id,
                                "item_id": item.item_id, "revision": actor.revision, "value": item.pet_slug})
    return sorted(sources, key=lambda row: json.dumps(row, sort_keys=True))


def character_source_fingerprint(sources: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def character_migration_choice(sources: list[dict[str, Any]], *, persona: bool) -> tuple[str, str | None]:
    if any(source["value"] is None for source in sources):
        raise CharacterAssignmentRefused(CharacterAssignmentReason.CONFLICT, "A placement inherits a legacy choice whose ownership needs review.")
    choices = {_legacy_choice(source["value"]) for source in sources}
    if len(choices) > 1:
        raise CharacterAssignmentRefused(CharacterAssignmentReason.CONFLICT, "Existing character choices disagree; select the intended character explicitly.")
    return next(iter(choices)) if choices else ("unassigned" if persona else "inherit", None)


def _legacy_choice(value: Any) -> tuple[str, str | None]:
    if not isinstance(value, str):
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Invalid legacy character value.")
    normalized = value.strip()
    mode, asset = ("assigned", normalized) if normalized else ("unassigned", None)
    validate_character_choice(mode, asset)
    return mode, asset


def guard_legacy_character_edit(request: Any, existing: Any, items: list[Any]) -> None:
    """Moves still work; an old client cannot change migrated appearance."""
    from .errors import NotFound
    from .config.roster import ensure_persisted_personas
    from .persona_assignments.store import PersonaInstanceStore

    if not request.persona_id or not any(item.kind == "agent" for item in items):
        return
    try:
        record = (PersonaInstanceStore().get(request.persona_instance_id) if request.persona_instance_id
                  else next((p for p in ensure_persisted_personas() if p.id == request.persona_id), None))
    except (FileNotFoundError, NotFound):
        return
    if record is None or record.character_assignment is None:
        return
    before = {item.item_id: item.pet_slug for item in existing.items if item.kind == "agent"} if existing else {}
    if any(item.kind == "agent" and item.pet_slug != before.get(item.item_id) for item in items):
        raise CharacterAssignmentRefused(CharacterAssignmentReason.MIGRATED, "Character choices now belong to the agent record. Update this client to edit its character.")
