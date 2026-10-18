"""Immutable Work scope and bounded wire values.

A Work owner is a WORKSPACE (plan ``work-on-markdown-2026-10-18.md`` §6.2): its todo board is the
brain queue notes of every repo slot it binds. ``Reason`` and ``WorkRefused`` are the work store's
one enum, re-exported here so the wire keeps its old import path.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from agent_runtime.work_store.reasons import Reason, WorkRefused

__layer__ = "models"
__all__ = ["OPERATIONS", "Reason", "WorkRefused", "WorkScope", "fingerprint", "text"]

#: What an owner advertises on the wire (``capabilities`` / ``context`` are not owner operations).
OPERATIONS = ("inspect", "start", "assign", "claim", "release", "set_status", "done", "create_brain")


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
    workspace_id: str

    @property
    def owner(self):
        return fingerprint([self.install, self.workspace_id])

    def wire(self, label):
        return {"owner": self.owner, "workspace_id": self.workspace_id, "label": label,
                "operations": list(OPERATIONS)}
