"""Immutable Work scope and bounded wire values."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

__layer__ = "models"


class Reason(StrEnum):
    INVALID = "invalid_request"
    OWNER_CHANGED = "work_owner_changed"
    UNAVAILABLE = "work_unavailable"
    CONFLICT = "idempotency_conflict"
    DENIED = "scope_denied"
    UNKNOWN = "work_outcome_unknown"


class WorkRefused(ValueError):
    def __init__(self, reason: Reason):
        self.reason = reason
        super().__init__(reason.value)


def text(value, *, maximum=256, multiline=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or "\0" in value or (not multiline and any(ord(c) < 32 for c in value))):
        raise WorkRefused(Reason.INVALID)
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class WorkScope:
    install: str
    board: str
    profile: str
    database: str
    home: str

    @property
    def owner(self):
        return fingerprint([self.install, self.board, self.profile, self.database, self.home])

    def wire(self, label):
        return {"owner": self.owner, "board": self.board, "profile": self.profile,
                "label": label, "operations": ["inspect", "start"]}
