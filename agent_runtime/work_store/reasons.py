"""Every Work refusal, one enum (plan ``work-on-markdown-2026-10-18.md`` §6.1, §8).

The first six are ``agent_runtime/work/model.py::Reason`` verbatim (W2 turns that one into a
re-export of this); the rest are the write path's step-table branches (§5) and the default
brain's. The dispatcher plan's B1 EXTENDS this enum; it never opens a second one.
"""

from __future__ import annotations

from enum import StrEnum

__layer__ = "models"
__all__ = ["Reason", "WorkRefused"]


class Reason(StrEnum):
    INVALID = "invalid_request"
    OWNER_CHANGED = "work_owner_changed"
    UNAVAILABLE = "work_unavailable"
    CONFLICT = "idempotency_conflict"
    DENIED = "scope_denied"
    UNKNOWN = "work_outcome_unknown"
    ROW_GONE = "row_gone"
    ALREADY_TAKEN = "already_taken"
    NOT_CLAIMANT = "not_claimant"
    ID_EXISTS = "id_exists"
    PUSH_CONTENDED = "push_contended"
    PUSH_REFUSED = "push_refused"
    SLOT_UNBOUND = "slot_unbound"
    GRAMMAR_INVALID = "grammar_invalid"
    NOTE_MISSING = "note_missing"
    BRANCH_MISSING = "branch_missing"
    REMOTE_MISSING = "remote_missing"
    FETCH_FAILED = "fetch_failed"
    WORKTREE_FAILED = "worktree_failed"
    WORKTREE_DIRTY = "worktree_dirty"
    COMMIT_FAILED = "commit_failed"
    GIT_UNAVAILABLE = "git_unavailable"
    MACHINE_UNIDENTIFIED = "machine_identity_unavailable"
    NO_BRAIN = "no_brain"
    NEEDS_PUBLISH_RIGHT = "needs_publish_right"
    ASSIGNEE_UNKNOWN = "assignee_unknown"


class WorkRefused(ValueError):
    """A Work request refused with a typed ``reason`` (the wire word) and an optional ``detail``."""

    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(detail or reason.value)
        self.reason = reason
        self.detail = detail
