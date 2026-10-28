"""The ``proposal_evidence`` table: why a proposing agent grouped a money ``best_of`` (W5).

Plan ``planned/lens-deadline-schedule-equivalence-report-2026-10-27.md`` §3 decision 3. A new module
beside ``store.py`` (that file sits under its ADR 0007 ceiling), opened through
:meth:`~agent_runtime.lens.store.LensStore.connection` as ``store_shapes.py`` is.

``lens_propose`` of a monitor whose rule is a money ``best_of`` must carry
``equivalence: {<feed_id>: {why, cited}}`` — one entry per member, nothing else
(:func:`read_equivalence`; ``equivalence_unjustified`` otherwise). ``why`` is at most
:data:`MAXIMUM_WHY_BYTES`, ``cited`` at most :data:`MAXIMUM_CITED` strings of at most
:data:`MAXIMUM_CITED_BYTES` the agent read (a listing's title, its item specifics).

It is PROPOSAL EVIDENCE, not sealed bytes: one row per monitor, keyed by the canonical digest of the
draft it justified (the digest a seal of that draft would carry). :func:`equivalence_evidence` is what
``runtime.lens.get`` returns as ``equivalence_evidence``, with ``stale: true`` once the monitor's
current manifest (its draft, else its sealed revision) is no longer that draft. The text is
source-derived (W9): the operator sees it as untrusted data, and nothing re-feeds it to a turn.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import Any

from .manifest import read_manifest
from .store import LensStore, to_ms
from .wire_value import (
    WireError,
    WireRefusal,
    bounded_list,
    bounded_string,
    canonical_digest,
    checked_object,
    require,
)

__layer__ = "stores"

MAXIMUM_WHY_BYTES = 512
MAXIMUM_CITED = 4
MAXIMUM_CITED_BYTES = 256
ENTRY_KEYS = frozenset({"why", "cited"})

_SCHEMA = """CREATE TABLE IF NOT EXISTS proposal_evidence (
  monitor_id TEXT PRIMARY KEY, draft_digest TEXT NOT NULL, body TEXT NOT NULL, updated_ms INTEGER NOT NULL)"""


def _read_entry(value: Any) -> dict[str, Any]:
    m = checked_object(value, ENTRY_KEYS)
    return {"why": bounded_string(m["why"], maximum=MAXIMUM_WHY_BYTES, layout=True),
            "cited": bounded_list(m["cited"], lambda item: bounded_string(item, maximum=MAXIMUM_CITED_BYTES),
                                  maximum=MAXIMUM_CITED)}


def read_equivalence(value: Any, members: list[str]) -> dict[str, Any]:
    """One justification per member of the money ``best_of`` group, and none for anything else."""

    if value is None:
        raise WireError(WireRefusal.EQUIVALENCE_UNJUSTIFIED, "equivalence")
    m = checked_object(value, (), members)
    if set(m) != set(members):
        raise WireError(WireRefusal.EQUIVALENCE_UNJUSTIFIED, "equivalence")
    return {feed_id: _read_entry(m[feed_id]) for feed_id in members}


def draft_digest(manifest: dict[str, Any]) -> str:
    """The digest a seal of ``manifest`` would carry (``seal.seal_manifest``: sha256 of canonical bytes)."""

    return canonical_digest(read_manifest(manifest))


def record_evidence(store: LensStore, monitor_id: str, digest: str, evidence: dict[str, Any]) -> None:
    require(bool(evidence), "equivalence")
    with store.connection() as conn:
        conn.execute(_SCHEMA)
        conn.execute("INSERT OR REPLACE INTO proposal_evidence (monitor_id, draft_digest, body, updated_ms) "
                     "VALUES (?, ?, ?, ?)", (monitor_id, digest, json.dumps(evidence, sort_keys=True),
                                                         to_ms(datetime.now(UTC))))


def equivalence_evidence(store: LensStore, monitor: dict[str, Any]) -> dict[str, Any] | None:
    """``{draft_digest, stale, members}`` for ``monitor`` (a ``LensStore.get`` summary), or None."""

    if not store.exists():
        return None
    with store.connection() as conn:
        conn.execute(_SCHEMA)
        row = conn.execute("SELECT draft_digest, body FROM proposal_evidence WHERE monitor_id = ?",
                           (monitor["monitor_id"],)).fetchone()
    if row is None:
        return None
    if monitor["draft"] is not None:
        current = draft_digest(monitor["draft"])
    else:
        current = (monitor["sealed"] or {}).get("digest")
    return {"draft_digest": row[0], "stale": current != row[0], "members": json.loads(row[1])}
