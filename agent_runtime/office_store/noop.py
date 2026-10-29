"""The office no-op rule: a content-equal write writes nothing.

An office write whose next row differs from the live row only in the
bookkeeping a write stamps — ``revision``, ``updated_at``, ``updated_by`` and
the ``created_at`` the next row copies — changed nothing, so it writes no
file, bumps no revision and emits no event; the write door acks the live row
(``docs/agent-runtime-harness/planned/office-page-open-write-storm.md`` §3).

Pure: no store, no lock, no file. The write lanes decide WHEN the rule may
answer (after every fence and the revision check, for a LIVE row only); this
module answers only WHETHER two rows are equal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from agent_runtime.serde import to_jsonable

__layer__ = "policy"

__all__ = [
    "VOLATILE_FIELDS",
    "WriteOutcome",
    "unchanged",
]

#: The fields a write stamps rather than carries. Two rows equal everywhere
#: else are the same content.
VOLATILE_FIELDS: frozenset[str] = frozenset({"revision", "updated_at", "updated_by", "created_at"})

RowT = TypeVar("RowT")


@dataclass(frozen=True, slots=True)
class WriteOutcome(Generic[RowT]):
    """One office write's answer: the row the caller acks, and whether a file
    was written. ``written=False`` with a live row is the no-op; a dry run is
    also ``written=False`` and carries the would-be row."""

    row: RowT
    written: bool


def _content(row: Any) -> dict[str, Any]:
    raw = to_jsonable(row)
    if not isinstance(raw, dict):
        raise TypeError(f"unchanged() compares dataclass rows, got {type(row).__name__}")
    return {key: value for key, value in raw.items() if key not in VOLATILE_FIELDS}


def unchanged(existing: Any, candidate: Any) -> bool:
    """True iff ``candidate`` equals ``existing`` outside :data:`VOLATILE_FIELDS`."""
    if type(existing) is not type(candidate):
        return False
    return _content(existing) == _content(candidate)
