"""Non-spatial discussion configuration and execution-only projections."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .definitions import Configuration, DefinitionError, DiscussionSettings, ParticipantRef, fields, _name

__layer__ = "stores"

ROOM_MEMBER_LIMIT = 9


@dataclass(frozen=True, slots=True)
class RoomSpec:
    name: str
    participants: tuple[ParticipantRef, ...]
    settings: DiscussionSettings

    @classmethod
    def parse(cls, value: Any) -> RoomSpec:
        value = fields(value, {"name", "participants", "settings"}, field="discussion")
        config = Configuration.parse({"participants": value["participants"],
            "settings": value["settings"], "seat_preferences": []})
        if not 2 <= len(config.participants) <= ROOM_MEMBER_LIMIT:
            raise DefinitionError("invalid_room_member_count", "participants")
        return cls(_name(value["name"]), config.participants, config.settings)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "participants": [p.to_dict() for p in self.participants],
                "settings": self.settings.to_dict()}


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    name: str
    settings: Mapping[str, Any]
    capacity: int


def execution_spec(run: Mapping[str, Any]) -> ExecutionSpec:
    """Placement is optional; both admissions use the same native executor."""
    initial = run["initial"]
    if "discussion" in initial:
        spec = initial["discussion"]
        return ExecutionSpec(spec["name"], spec["settings"], ROOM_MEMBER_LIMIT)
    spec = initial["table"]["spec"]
    return ExecutionSpec(spec["name"], spec["configuration"]["settings"], initial["seat_plan"]["capacity"])
