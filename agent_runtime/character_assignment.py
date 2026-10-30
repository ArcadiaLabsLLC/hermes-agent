"""Character assignment values on existing persona/instance records.

The record owns appearance, not placement, renderer or runtime activity. An
absent record means legacy authority; inherit, unassigned and assigned are
distinct durable choices. Stores own writes; this module only validates values.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__layer__ = "models"


class CharacterAssignmentReason(StrEnum):
    INVALID = "invalid_character_assignment"
    STALE = "stale_character_revision"
    CONFLICT = "character_migration_conflict"
    MIGRATED = "character_assignment_migrated"
    UNKNOWN_VERSION = "unsupported_character_assignment_version"


class CharacterAssignmentRefused(ValueError):
    def __init__(self, reason: CharacterAssignmentReason, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class CharacterAssignmentMode(StrEnum):
    INHERIT = "inherit"
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"


@dataclass(frozen=True)
class CharacterModeRules:
    carries_asset: bool
    persona_allowed: bool
    inherits_persona: bool


_CHARACTER_MODE_RULES = {
    CharacterAssignmentMode.INHERIT: CharacterModeRules(False, False, True),
    CharacterAssignmentMode.UNASSIGNED: CharacterModeRules(False, True, False),
    CharacterAssignmentMode.ASSIGNED: CharacterModeRules(True, True, False),
}


def validate_character_choice(mode: Any, asset: Any, *, persona: bool = False) -> None:
    rules = _CHARACTER_MODE_RULES.get(mode) if isinstance(mode, str) else None
    if rules is None or (persona and not rules.persona_allowed):
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Invalid assignment mode.")
    if not rules.carries_asset:
        if asset is not None:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Only assigned may carry an asset.")
        return
    # Same storage vocabulary as CharacterAssetReference: bare Petdex slug or
    # chara:<id>. Do not reinterpret a bare value as an agent/persona id.
    if (not isinstance(asset, str) or not asset.strip() or asset != asset.strip()
            or len(asset) > 512 or any(ord(char) < 32 for char in asset)
            or (asset.startswith("chara:") and not asset[6:].strip())):
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Invalid character asset reference.")


def validate_character_record(record: Any, *, persona: bool = False) -> dict[str, Any] | None:
    if record is None:
        return None
    if not isinstance(record, dict) or type(record.get("version")) is not int or record.get("version") != 1:
        raise CharacterAssignmentRefused(CharacterAssignmentReason.UNKNOWN_VERSION, "Unsupported assignment record.")
    revision = record.get("revision")
    if type(revision) is not int or revision < 1:
        raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "Invalid assignment revision.")
    validate_character_choice(record.get("mode"), record.get("asset_reference"), persona=persona)
    return record


@dataclass(frozen=True)
class CharacterAssignmentChange:
    expected_revision: int
    mode: str
    asset_reference: str | None
    operation_id: str
    migration_receipt: dict[str, Any] | None = None

    def apply(self, current: Any, *, persona: bool = False) -> dict[str, Any]:
        validate_character_choice(self.mode, self.asset_reference, persona=persona)
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "A read revision is required.")
        if not isinstance(self.operation_id, str) or not self.operation_id.strip() or len(self.operation_id) > 128:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.INVALID, "An operation id is required.")
        current = validate_character_record(current, persona=persona)
        choice = {"mode": self.mode, "asset_reference": self.asset_reference}
        if current is not None and current.get("operation_id") == self.operation_id:
            if all(current.get(key) == value for key, value in choice.items()):
                return deepcopy(current)
            raise CharacterAssignmentRefused(CharacterAssignmentReason.CONFLICT, "Operation id was reused for another choice.")
        if (current["revision"] if current else 0) != self.expected_revision:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.STALE, "Read the current assignment before saving.")
        return {
            "version": 1, "revision": self.expected_revision + 1,
            **choice, "operation_id": self.operation_id,
            "migration_receipt": deepcopy(current.get("migration_receipt") if current else self.migration_receipt),
        }


@dataclass(frozen=True)
class CharacterAssignmentReplication:
    expected_record: dict[str, Any] | None
    incoming_record: dict[str, Any] | None

    def apply(self, current: Any, *, persona: bool = False) -> dict[str, Any] | None:
        if current != self.expected_record:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.STALE, "The local assignment changed during realm adoption.")
        incoming = validate_character_record(self.incoming_record, persona=persona)
        if current is not None and incoming is None:
            raise CharacterAssignmentRefused(CharacterAssignmentReason.CONFLICT, "An older peer cannot remove record ownership.")
        return deepcopy(incoming)


def preserve_character_assignment(model: Any, stored: dict[str, Any], change: CharacterAssignmentChange | CharacterAssignmentReplication | None = None) -> None:
    """Called inside the owning store's row lock before its existing write.

    Unrelated whole-row saves cannot mutate this field, including stale copies
    loaded before migration. Unknown future records are retained verbatim.
    """
    current = stored.get("character_assignment") if stored else getattr(model, "character_assignment", None)
    model.character_assignment = deepcopy(current) if change is None else change.apply(
        current, persona=not hasattr(model, "persona_id"),
    )


def resolve_character_assignment(instance: Any, persona: Any) -> dict[str, Any]:
    """A read projection; inheritance follows the persona live, never a copy."""
    try:
        own = validate_character_record(getattr(instance, "character_assignment", None))
        default = validate_character_record(getattr(persona, "character_assignment", None), persona=True)
    except CharacterAssignmentRefused as exc:
        return {"authority": "unavailable", "reason": exc.reason.value}
    effective = default if own is None or _CHARACTER_MODE_RULES[own["mode"]].inherits_persona else own
    return {
        "instance": deepcopy(own), "persona": deepcopy(default),
        "authority": "record" if own is not None else "legacy",
        "mode": effective["mode"] if effective else "inherit",
        "asset_reference": effective.get("asset_reference") if effective else None,
    }
