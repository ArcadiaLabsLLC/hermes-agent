"""Profile-backed groups: explicit bindings, without persona or office creation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agent_runtime.conversations.model import ConversationScope, conversation_route_id
from .definitions import DefinitionError, DiscussionSettings, fields, identifier, _name
from .run_values import DiscussionError, digest

__layer__ = "stores"

SCOPE_PREFIX = "conversation-scope-"


def group_scope(actor: str, client: str) -> str:
    identifier(client, "client_scope")
    return SCOPE_PREFIX + digest({"actor": actor, "client": client})[:40]


def is_group_scope(value: str) -> bool:
    return value.startswith(SCOPE_PREFIX)


@dataclass(frozen=True, slots=True)
class ProfileParticipant:
    install_id: str
    profile: str
    home: str
    name: str

    @classmethod
    def parse(cls, value: Any) -> ProfileParticipant:
        value = fields(value, {"install_id", "profile", "home", "name"}, field="participant")
        profile = identifier(value["profile"], "profile")
        home = value["home"]
        if not isinstance(home, str) or not Path(home).is_absolute() or len(home) > 4096:
            raise DefinitionError("invalid_profile_home", "home")
        return cls(identifier(value["install_id"], "install_id"), profile,
                   str(Path(home).resolve()), _name(value["name"]))

    @property
    def member_id(self) -> str:
        return "m-" + digest({"install": self.install_id, "profile": self.profile, "home": self.home})[:24]

    def to_dict(self) -> dict[str, str]:
        return {"install_id": self.install_id, "profile": self.profile, "home": self.home, "name": self.name}


@dataclass(frozen=True, slots=True)
class ProfileGroupSpec:
    name: str
    participants: tuple[ProfileParticipant, ...]
    cwd: str

    @classmethod
    def parse(cls, value: Any) -> ProfileGroupSpec:
        value = fields(value, {"name", "participants", "cwd"}, field="group")
        rows = value["participants"]
        if not isinstance(rows, list) or not 2 <= len(rows) <= 9:
            raise DefinitionError("invalid_room_member_count", "participants")
        members = tuple(ProfileParticipant.parse(row) for row in rows)
        if len({(m.install_id, m.profile) for m in members}) != len(members):
            raise DefinitionError("duplicate_participant", "participants")
        cwd = value["cwd"]
        if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
            raise DefinitionError("invalid_directory", "cwd")
        return cls(_name(value["name"]), members, str(Path(cwd).resolve()))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "participants": [p.to_dict() for p in self.participants], "cwd": self.cwd}


def group_initial(spec: ProfileGroupSpec, actor: str, client: str) -> dict[str, Any]:
    return {"group": {**spec.to_dict(), "actor": actor, "client": client,
                      "settings": DiscussionSettings(3, True, False, None).to_dict()}}


def profile_member(run_id: str, ref: ProfileParticipant, actor: str, client: str,
                   *, install_id: str) -> dict[str, Any]:
    if ref.install_id != install_id:
        raise DiscussionError("remote_members_not_supported")
    scope = ConversationScope(actor, client, ref.profile)
    return {"member_id": ref.member_id, "install_id": ref.install_id,
            "instance_id": None, "persona_id": None, "profile": ref.profile,
            "display_name": ref.name, "session_id": conversation_route_id(scope, run_id),
            "binding": ref.to_dict()}


def member_scope(run: Mapping[str, Any], member: Mapping[str, Any]) -> ConversationScope:
    group = run["initial"]["group"]
    return ConversationScope(group["actor"], group["client"], member["profile"])
