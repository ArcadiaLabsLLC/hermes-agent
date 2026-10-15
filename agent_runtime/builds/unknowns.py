"""The typed-unknown index: everything hermes could not classify about a build, WITH what it saw.

Owner rule 2026-10-04, "index the unknowns" (plan
``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §1 ``unknowns``):
an unrecognised stage line, unreadable output, an unidentifiable process, an
environment or wrapper hermes could not observe — each is recorded on the row (or the
registry record, or a source's sub-health) as ``{kind, evidence, seen_at}``, so a future
problem is debuggable from the record instead of from someone's memory.

The index is a per-row WIRE bound like ``TAIL_PREVIEW_LIMIT``, not a model limit:
:data:`UNKNOWNS_WIRE_LIMIT` entries, deduplicated by ``kind`` + evidence hash, the
NEWEST kept, and a truncation declared ``by_design`` through the projection accountant
(``unknowns_truncated``) so a deliberate bound never reads as lost data. Evidence is
redacted (secret-shaped assignments masked in place) and bounded to
:data:`EVIDENCE_LIMIT` characters. An EMPTY index is itself a claim — "nothing was
unclassifiable" — which is why a kind outside :data:`UNKNOWN_KINDS` is refused rather
than recorded: an untyped unknown would be a second, unenumerable vocabulary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from agent_runtime.projection_accountant import ProjectionAccountant
from agent_runtime.redaction import TEXT_SECRET_ASSIGNMENT_RE

__layer__ = "models"

UNKNOWN_STAGE_LINE_UNRECOGNIZED = "stage_line_unrecognized"
UNKNOWN_OUTPUT_UNREADABLE = "output_unreadable"
UNKNOWN_PROCESS_UNIDENTIFIED = "process_unidentified"
UNKNOWN_CWD_UNREADABLE = "cwd_unreadable"
UNKNOWN_WRAPPER_UNOBSERVED = "wrapper_unobserved"
UNKNOWN_ENV_UNOBSERVED = "env_unobserved"
UNKNOWN_PATH_UNOBSERVED = "path_unobserved"
UNKNOWN_ARTIFACT_UNLOCATED = "artifact_unlocated"
UNKNOWN_WRITER_UNIDENTIFIED = "writer_unidentified"
UNKNOWN_SLOT_UNRESOLVED = "slot_unresolved"
UNKNOWN_SLOT_UNBOUND_HERE = "slot_unbound_here"
UNKNOWN_SLOT_PROBE_UNKNOWN = "slot_probe_unknown"
UNKNOWN_TOOLCHAIN_UNRECOGNIZED = "toolchain_unrecognized"
#: OWNER 2026-10-04 (example): the persona instance whose turn started a build did not resolve.
UNKNOWN_STARTER_UNKNOWN = "starter_unknown"

#: Every kind an unknown may carry, in the plan's order. The wire vocabulary: a consumer
#: renders these words, the fixture file enumerates them from here.
UNKNOWN_KINDS = (
    UNKNOWN_STAGE_LINE_UNRECOGNIZED,
    UNKNOWN_OUTPUT_UNREADABLE,
    UNKNOWN_PROCESS_UNIDENTIFIED,
    UNKNOWN_CWD_UNREADABLE,
    UNKNOWN_WRAPPER_UNOBSERVED,
    UNKNOWN_ENV_UNOBSERVED,
    UNKNOWN_PATH_UNOBSERVED,
    UNKNOWN_ARTIFACT_UNLOCATED,
    UNKNOWN_WRITER_UNIDENTIFIED,
    UNKNOWN_SLOT_UNRESOLVED,
    UNKNOWN_SLOT_UNBOUND_HERE,
    UNKNOWN_SLOT_PROBE_UNKNOWN,
    UNKNOWN_TOOLCHAIN_UNRECOGNIZED,
    UNKNOWN_STARTER_UNKNOWN,
)

#: Per-row wire bound on the index. Truncation is declared ``by_design``.
UNKNOWNS_WIRE_LIMIT = 32
#: Per-entry evidence bound, in characters, after redaction.
EVIDENCE_LIMIT = 200
#: The accountant reason a truncated index records (by design).
UNKNOWNS_TRUNCATED = "unknowns_truncated"


def redact_evidence(value: Any) -> str:
    """Whitespace-collapsed, secret-masked, ``EVIDENCE_LIMIT``-bounded evidence text.

    The same ruling ``running_work.rows.bounded_operator_text`` applies (paths are the
    CONTENT on an operator console; only secret-shaped assignments are masked, in place).
    """

    if value is None:
        return ""
    text = " ".join(str(value).split())
    text = TEXT_SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}: [redacted]", text)
    if len(text) > EVIDENCE_LIMIT:
        return text[: EVIDENCE_LIMIT - 1] + "…"
    return text


@dataclass(frozen=True)
class Unknown:
    """One typed unknown: what could not be classified, what was seen, and when."""

    kind: str
    evidence: str
    seen_at: float

    @property
    def key(self) -> tuple[str, str]:
        """The dedup key: the kind plus a hash of the (redacted) evidence."""

        return self.kind, hashlib.sha256(self.evidence.encode("utf-8")).hexdigest()[:16]

    def wire(self) -> dict[str, Any]:
        return {"kind": self.kind, "evidence": self.evidence, "seen_at": self.seen_at}


def unknown(kind: str, evidence: Any, seen_at: float) -> Unknown:
    """A validated :class:`Unknown`; a kind outside :data:`UNKNOWN_KINDS` raises ``ValueError``."""

    if kind not in UNKNOWN_KINDS:
        raise ValueError(f"unknown kind {kind!r} is not one of UNKNOWN_KINDS")
    return Unknown(kind=kind, evidence=redact_evidence(evidence), seen_at=float(seen_at))


class UnknownsIndex:
    """A bounded, deduplicated, newest-kept index of :class:`Unknown` entries.

    Adding an entry whose ``(kind, evidence hash)`` is already present REPLACES it with
    the newer sighting (the later ``seen_at`` wins), so a stage line seen on every poll is
    one entry, not thirty-two. :meth:`wire` emits at most ``limit`` entries, oldest first,
    keeping the newest, and declares any truncation ``by_design``.
    """

    def __init__(self, entries: Iterable[Unknown] = (), *, limit: int = UNKNOWNS_WIRE_LIMIT) -> None:
        self._limit = max(0, int(limit))
        self._entries: dict[tuple[str, str], Unknown] = {}
        for entry in entries:
            self._put(entry)

    def _put(self, entry: Unknown) -> None:
        held = self._entries.pop(entry.key, None)
        if held is not None and held.seen_at > entry.seen_at:
            entry = held
        self._entries[entry.key] = entry

    def add(self, kind: str, evidence: Any, seen_at: float) -> None:
        self._put(unknown(kind, evidence, seen_at))

    def extend_wire(self, entries: Any) -> int:
        """Merge a writer's own wire list; returns how many entries were not typed unknowns.

        A writer that wrote a kind this vocabulary does not know is refused entry rather
        than coerced: the count lets the caller say so instead of silently dropping it.
        """

        refused = 0
        for item in entries if isinstance(entries, list) else ():
            try:
                self.add(str(item["kind"]), item.get("evidence"), float(item.get("seen_at") or 0.0))
            except (KeyError, TypeError, ValueError, AttributeError):
                refused += 1
        return refused

    def __len__(self) -> int:
        return len(self._entries)

    def kinds(self) -> set[str]:
        return {entry.kind for entry in self._entries.values()}

    @property
    def truncated(self) -> int:
        return max(0, len(self._entries) - self._limit)

    def wire(self, accountant: ProjectionAccountant | None = None, *, entity_id: str = "") -> list[dict[str, Any]]:
        ordered = sorted(self._entries.values(), key=lambda entry: entry.seen_at)
        dropped = self.truncated
        if dropped and accountant is not None:
            accountant.drop(
                UNKNOWNS_TRUNCATED,
                count=dropped,
                entity_id=entity_id,
                detail=f"unknowns index bounded to {self._limit} entries, newest kept",
                by_design=True,
            )
        return [entry.wire() for entry in ordered[dropped:]]
