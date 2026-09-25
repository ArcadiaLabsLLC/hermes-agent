"""The retired-instance archive layout: the ``*_retire`` batch directories, the
per-id archive path, the retire receipt path, and the retired-id set every mint
consults.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_runtime import paths
from agent_runtime.persona_assignments.tokens import safe_assignment_token

__layer__ = "stores"

__all__ = [
    "retire_receipt_path",
    "RETIRE_RECEIPTS_DIRNAME",
    "retired_persona_instance_ids",
    "_retire_archive_batches",
    "_retired_persona_instance_archive_path",
]


def _retire_archive_batches() -> list[Path]:
    """Newest-first ``*_retire`` batch directories under the instance archive.

    THE selection rule for retirement tombstones, in one place: only ``*_retire``
    batches are tombstones. Reconcile/prune archives answer different lifecycle
    questions and must not make a future legitimate mint impossible. Both the
    per-id probe (:func:`_retired_persona_instance_archive_path`) and the
    whole-archive listing (:func:`retired_persona_instance_ids`) read the archive
    through this, so a second, subtly different notion of "retired" cannot be
    born by one of them widening its glob.
    """
    archive_root = paths.persona_instances_archive_dir()
    if not archive_root.exists():
        return []
    return sorted(
        (
            candidate
            for candidate in archive_root.iterdir()
            if candidate.is_dir() and candidate.name.endswith("_retire")
        ),
        key=lambda candidate: candidate.name,
        reverse=True,
    )


def _retired_persona_instance_archive_path(
    persona_instance_id: str,
) -> Path | None:
    """Newest explicit-retire archive row for ``persona_instance_id``.

    Exact child paths avoid treating the instance id as a glob.
    """
    for archive_dir in _retire_archive_batches():
        candidate = archive_dir / f"{persona_instance_id}.json"
        if candidate.is_file():
            return candidate
    return None


#: The retire receipt subdirectory inside a ``*_retire`` batch. A SUBDIRECTORY
#: and never a sibling file, because every ``*.json`` FILE directly inside a
#: batch is read as a tombstone by :func:`retired_persona_instance_ids` — it
#: takes ``row.stem`` as the instance id — so a receipt written beside the row
#: would mint a phantom retired id and the retirement predicate would start
#: refusing legitimate mints for an agent that never existed. ``iterdir`` skips
#: directories and the per-id probe asks for an exact child, so this name is
#: invisible to both by construction rather than by their remembering to skip it.
RETIRE_RECEIPTS_DIRNAME = "receipts"


def retire_receipt_path(archive_dir: Path, persona_instance_id: str) -> Path:
    """Where THIS retire's receipt lives — the one layout authority, both ways.

    Spent by the writer (:meth:`PersonaInstanceStore.retire`) and by the reader
    (:meth:`PersonaInstanceStore.read_retire_receipt`), so the batch layout is
    stated once. See :data:`RETIRE_RECEIPTS_DIRNAME` for why it is a
    subdirectory.
    """

    return archive_dir / RETIRE_RECEIPTS_DIRNAME / f"{persona_instance_id}.json"


def retired_persona_instance_ids() -> frozenset[str]:
    """Every instance id carrying a retirement tombstone, in ONE archive listing.

    The ARCHIVE half of the retirement predicate, for readers that must answer
    "was this id deliberately retired?" for MANY ids at once — a snapshot
    projection walking its sessions, say. The per-id probe
    (:meth:`PersonaInstanceStore.retired_instance_archive_path`) stays the
    predicate of record for a single target because it also composes the LIVE
    half (a live row always wins); a caller of this listing must supply that half
    itself, which the projection callers do by construction — they only ask after
    an id has already failed to resolve against the live roster they hold.

    Read once and memoized by the caller for the length of its build, never
    re-walked per row: the archive is ~one directory per retire, forever.

    NEVER RAISES. The listing is filesystem I/O over a store root that is
    routinely a flaky UNC share on this runtime; a reader that cannot see the
    archive cannot PROVE a retirement, so it reports the empty set (every id
    stays unresolved/anomalous — the loud, pre-fix posture) and logs.
    """
    ids: set[str] = set()
    try:
        for archive_dir in _retire_archive_batches():
            for row in archive_dir.iterdir():
                if row.is_file() and row.suffix == ".json":
                    instance_id = safe_assignment_token(row.stem)
                    if instance_id:
                        ids.add(instance_id)
    except OSError:
        logging.getLogger(__name__).warning(
            "persona-instance retirement archive listing failed; "
            "treating every instance as NOT retired",
            exc_info=True,
        )
        return frozenset()
    return frozenset(ids)
