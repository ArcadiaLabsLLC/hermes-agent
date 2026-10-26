"""Immutable Work scope and bounded wire values.

A Work owner is a WORKSPACE (plan ``work-on-markdown-2026-10-18.md`` §6.2): its todo board is the
brain queue notes of every repo slot it binds. The general todo (plan ``general-todo-2026-10-25.md``
§2.2) adds a board ``kind``: ``workspace`` (that), ``personal`` (the operator's machine-local board, one
per namespace) and ``agent`` (a VIEW — the rows assigned to one persona instance across the boards it
can see; never an owner, never storage). ``Reason`` and ``WorkRefused`` are the work store's
one enum, re-exported here so the wire keeps its old import path.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from agent_runtime.work_store.reasons import Reason, WorkRefused

__layer__ = "models"
__all__ = ["BOARD_KINDS", "KIND_AGENT", "KIND_PERSONAL", "KIND_WORKSPACE", "OPERATIONS", "READ_METHOD_PARAMS", "Reason", "WorkRefused", "WorkScope", "fingerprint", "text"]

#: The keys the three READ methods honour, published in the rpc manifest's ``params`` block so a passive
#: reader sees ``observe`` in the greeting before its first call (RT-WORK-OBSERVE-MANIFEST-PARAMS: an older
#: runtime answers ``capabilities`` by provisioning). Sorted; ``service`` / ``store`` / ``context`` read them.
_SCOPED = ("client_scope", "conversation", "install_id", "owner")
READ_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.work.capabilities": ("observe",),
    "runtime.work.inspect": tuple(sorted((*_SCOPED, "kind", "observe", "slot", "stale_ok", "task_id"))),
    "runtime.work.list": tuple(sorted((*_SCOPED, "assignee", "kind", "observe", "slot", "stale_ok", "status", "view"))),
}

#: What an owner advertises on the wire (``capabilities`` / ``context`` are not owner operations).
OPERATIONS = ("inspect", "start", "assign", "claim", "release", "set_status", "done", "create_brain", "lend_skills")


KIND_WORKSPACE = "workspace"
KIND_PERSONAL = "personal"
KIND_AGENT = "agent"
#: Advertised as ``capabilities.board_kinds``; ``agent`` is answered by ``list`` with ``kind: agent``.
BOARD_KINDS = (KIND_WORKSPACE, KIND_PERSONAL, KIND_AGENT)


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
    kind: str = KIND_WORKSPACE

    @property
    def owner(self):
        # A workspace owner keeps the fingerprint it always had; the personal board's carries its kind,
        # so it can never answer for a workspace that happens to share its id.
        if self.kind == KIND_WORKSPACE:
            return fingerprint([self.install, self.workspace_id])
        return fingerprint([self.install, self.kind, self.workspace_id])

    def wire(self, label):
        return {"owner": self.owner, "workspace_id": self.workspace_id, "kind": self.kind, "label": label,
                "operations": list(OPERATIONS)}
