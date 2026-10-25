"""Strict explicit member bindings for profile-group adoption."""
from __future__ import annotations

from .definitions import DefinitionError, ParticipantRef, fields, identifier

__layer__ = "stores"


def member_targets(value):
    if not isinstance(value, list) or not 2 <= len(value) <= 128:
        raise DefinitionError("invalid_migration_members", "members")
    result = []
    for row in value:
        row = fields(row, {"member_id", "participant"}, field="members")
        result.append({"member_id": identifier(row["member_id"], "member_id"),
                       "participant": ParticipantRef.parse(row["participant"]).to_dict()})
    if len({r["member_id"] for r in result}) != len(result) or len({
            (r["participant"]["install_id"], r["participant"]["instance_id"]) for r in result}) != len(result):
        raise DefinitionError("duplicate_migration_member", "members")
    return sorted(result, key=lambda r: r["member_id"])
