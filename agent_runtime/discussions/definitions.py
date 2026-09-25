"""Immutable discussion-table and preset values, independent of live agents.

A configuration names instances, never profiles. Validation establishes shape,
not existence, permission, readiness or turn ownership: native admission still
owns those decisions. A preset is a copied recipe, not a permanent group.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

__layer__ = "stores"

CAPACITIES = (2, 4, 6, 8, 10, 12)
MAX_PARTICIPANTS = CAPACITIES[-1]
MAX_REVISION = 2**53 - 1  # Lossless in JSON clients as well as Python/SQLite.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class DefinitionError(ValueError):
    """Stable reason and safe field coordinates, without echoing supplied data."""

    def __init__(self, reason: str, field: str, **details: Any) -> None:
        self.reason, self.field, self.details = reason, field, details
        super().__init__(f"{reason}: {field}")


class TableStyle(StrEnum):
    ROUND = "round"
    CONFERENCE = "conference"


def fields(value: Any, required: set[str], *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise DefinitionError("invalid_object", field)
    if set(value) != required:
        # Do not reflect untrusted key names (which may themselves contain secrets).
        raise DefinitionError("invalid_fields", field)
    return value


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise DefinitionError("invalid_identifier", field)
    return value


def revision(value: Any, field: str = "expect_revision", *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_REVISION:
        raise DefinitionError("invalid_revision", field)
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 1024:
        raise DefinitionError("invalid_name", "name")
    # Reject controls and invalid Unicode; do not silently rewrite identity labels.
    if any(unicodedata.category(c) in {"Cc", "Cs"} or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for c in value):
        raise DefinitionError("invalid_name", "name")
    value = value.strip()
    if not value or len(value.encode("utf-8")) > 256:
        raise DefinitionError("invalid_name", "name")
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise DefinitionError("invalid_boolean", field)
    return value


def _integer(value: Any, low: int, high: int, field: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise DefinitionError("invalid_integer", field)
    return value


def _number(value: Any, low: float, high: float, field: str) -> float:
    if type(value) not in (int, float):
        raise DefinitionError("invalid_number", field)
    try:
        result = float(value)
    except OverflowError as exc:
        raise DefinitionError("invalid_number", field) from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise DefinitionError("invalid_number", field)
    return 0.0 if result == 0 else result


def capacity(value: Any) -> int | str:
    if value == "auto" and isinstance(value, str):
        return value
    if type(value) is not int or value not in CAPACITIES:
        raise DefinitionError("invalid_capacity", "capacity")
    return value


def effective_capacity(requested: int | str, participant_count: int) -> int:
    requested = capacity(requested)
    participant_count = _integer(participant_count, 0, MAX_PARTICIPANTS, "participant_count")
    if requested == "auto":
        return next(size for size in CAPACITIES if size >= participant_count)
    if participant_count > requested:
        raise DefinitionError("capacity_exceeded", "participants", required=participant_count, capacity=requested)
    return requested


@dataclass(frozen=True, slots=True)
class ParticipantRef:
    install_id: str
    instance_id: str

    @classmethod
    def parse(cls, value: Any) -> ParticipantRef:
        value = fields(value, {"install_id", "instance_id"}, field="participant")
        install = identifier(value["install_id"], "install_id")
        instance = identifier(value["instance_id"], "instance_id")
        if not instance.startswith("personainst_") or instance == "personainst_":
            raise DefinitionError("invalid_instance_id", "instance_id")
        return cls(install, instance)

    def to_dict(self) -> dict[str, Any]:
        return {"install_id": self.install_id, "instance_id": self.instance_id}


@dataclass(frozen=True, slots=True)
class DiscussionSettings:
    rounds: int
    user_participates: bool
    allow_invitations: bool
    moderator: ParticipantRef | None

    @classmethod
    def parse(cls, value: Any) -> DiscussionSettings:
        value = fields(value, {"rounds", "user_participates", "allow_invitations", "moderator"}, field="settings")
        return cls(
            _integer(value["rounds"], 1, 3, "rounds"),
            _boolean(value["user_participates"], "user_participates"),
            _boolean(value["allow_invitations"], "allow_invitations"),
            ParticipantRef.parse(value["moderator"]) if value["moderator"] is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"rounds": self.rounds, "user_participates": self.user_participates,
                "allow_invitations": self.allow_invitations,
                "moderator": self.moderator.to_dict() if self.moderator is not None else None}


@dataclass(frozen=True, slots=True)
class SeatPreference:
    participant: ParticipantRef
    seat: int

    def to_dict(self) -> dict[str, Any]:
        return {"participant": self.participant.to_dict(), "seat": self.seat}


@dataclass(frozen=True, slots=True)
class Configuration:
    participants: tuple[ParticipantRef, ...]
    settings: DiscussionSettings
    seat_preferences: tuple[SeatPreference, ...]

    @classmethod
    def parse(cls, value: Any) -> Configuration:
        value = fields(value, {"participants", "settings", "seat_preferences"}, field="configuration")
        raw = value["participants"]
        if not isinstance(raw, list) or len(raw) > MAX_PARTICIPANTS:
            raise DefinitionError("invalid_participants", "participants")
        participants = tuple(ParticipantRef.parse(row) for row in raw)
        if len(set(participants)) != len(participants):
            raise DefinitionError("duplicate_participant", "participants")
        settings = DiscussionSettings.parse(value["settings"])
        if settings.moderator is not None and settings.moderator not in participants:
            raise DefinitionError("moderator_not_member", "moderator")
        raw_preferences = value["seat_preferences"]
        if not isinstance(raw_preferences, list) or len(raw_preferences) > len(participants):
            raise DefinitionError("invalid_seat_preferences", "seat_preferences")
        preferences: dict[ParticipantRef, SeatPreference] = {}
        occupied: set[int] = set()
        for raw_preference in raw_preferences:
            pref = fields(raw_preference, {"participant", "seat"}, field="seat_preference")
            participant = ParticipantRef.parse(pref["participant"])
            seat = _integer(pref["seat"], 0, MAX_PARTICIPANTS - 1, "seat")
            if participant not in participants:
                raise DefinitionError("seat_owner_not_member", "seat_preferences")
            if participant in preferences or seat in occupied:
                raise DefinitionError("duplicate_seat_preference", "seat_preferences")
            preferences[participant] = SeatPreference(participant, seat)
            occupied.add(seat)
        # Preference map order is immaterial; participant order is not.
        return cls(participants, settings, tuple(preferences[p] for p in participants if p in preferences))

    def to_dict(self) -> dict[str, Any]:
        return {"participants": [p.to_dict() for p in self.participants], "settings": self.settings.to_dict(),
                "seat_preferences": [p.to_dict() for p in self.seat_preferences]}


@dataclass(frozen=True, slots=True)
class TableTransform:
    position: tuple[float, float]  # Existing Mission Office planar coordinates, not screen pixels.
    rotation_radians: float
    scale: float

    @classmethod
    def parse(cls, value: Any) -> TableTransform:
        value = fields(value, {"position", "rotation_radians", "scale"}, field="transform")
        xy = value["position"]
        if not isinstance(xy, list) or len(xy) != 2:
            raise DefinitionError("invalid_position", "position")
        return cls(
            tuple(_number(c, -1_000_000, 1_000_000, "position") for c in xy),
            _number(value["rotation_radians"], -math.tau, math.tau, "rotation_radians"),
            _number(value["scale"], 0.25, 4.0, "scale"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"position": list(self.position), "rotation_radians": self.rotation_radians, "scale": self.scale}


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: str
    style: TableStyle
    capacity: int | str
    transform: TableTransform
    configuration: Configuration

    @classmethod
    def parse(cls, value: Any) -> TableSpec:
        value = fields(value, {"name", "style", "capacity", "transform", "configuration"}, field="table")
        try:
            style = TableStyle(value["style"])
        except (ValueError, TypeError) as exc:
            raise DefinitionError("invalid_style", "style") from exc
        requested = capacity(value["capacity"])
        configuration = Configuration.parse(value["configuration"])
        effective_capacity(requested, len(configuration.participants))
        return cls(_name(value["name"]), style, requested, TableTransform.parse(value["transform"]), configuration)

    @property
    def seat_count(self) -> int:
        return effective_capacity(self.capacity, len(self.configuration.participants))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "style": self.style.value, "capacity": self.capacity,
                "transform": self.transform.to_dict(), "configuration": self.configuration.to_dict()}


@dataclass(frozen=True, slots=True)
class PresetSpec:
    name: str
    preferred_capacity: int | str
    configuration: Configuration

    @classmethod
    def parse(cls, value: Any) -> PresetSpec:
        value = fields(value, {"name", "preferred_capacity", "configuration"}, field="preset")
        requested = capacity(value["preferred_capacity"])
        configuration = Configuration.parse(value["configuration"])
        effective_capacity(requested, len(configuration.participants))
        return cls(_name(value["name"]), requested, configuration)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "preferred_capacity": self.preferred_capacity,
                "configuration": self.configuration.to_dict()}


def apply_preset(table: TableSpec, preset: PresetSpec) -> TableSpec:
    """Copy the recipe, preserving the placed object's appearance and transform.

    Capacity changes require a separate explicit edit. The preferred preset size
    is advice, not permission to resize a table behind the operator's back.
    """
    candidate = replace(table, configuration=preset.configuration)
    return TableSpec.parse(candidate.to_dict())


@dataclass(frozen=True, slots=True)
class SeatPlan:
    capacity: int
    assignments: tuple[SeatPreference, ...]
    remapped: tuple[ParticipantRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"capacity": self.capacity, "assignments": [p.to_dict() for p in self.assignments],
                "remapped": [p.to_dict() for p in self.remapped]}


def plan_seats(table: TableSpec) -> SeatPlan:
    """Stable logical seat assignment; no navigation, animation or execution.

    Keep valid preferred indices, then fill lowest free indices in roster order.
    Out-of-range preferences are explicitly reported, not silently discarded.
    Prefab geometry will map these logical indices to actual seat sockets.
    """
    table = TableSpec.parse(table.to_dict())  # Callers may construct dataclasses directly.
    count = table.seat_count
    requested = {p.participant: p.seat for p in table.configuration.seat_preferences}
    assigned = {p: seat for p, seat in requested.items() if seat < count}
    free = iter(i for i in range(count) if i not in assigned.values())
    for participant in table.configuration.participants:
        if participant not in assigned:
            assigned[participant] = next(free)
    return SeatPlan(count,
                    tuple(SeatPreference(p, assigned[p]) for p in table.configuration.participants),
                    tuple(p for p in table.configuration.participants if requested.get(p, -1) >= count))
