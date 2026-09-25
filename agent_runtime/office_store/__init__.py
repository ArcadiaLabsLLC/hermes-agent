"""The office store package — the package map (program rule 16).

Entry points (what calls in): ``OfficeStore`` (the single write chokepoint for
the Mission Office domain — every office verb, the office RPC lane, realm sync
and the snapshot builder), ``read_actor_dir`` / ``ActorScan`` (the actor
directory read ``office_sync`` takes), and the typed outcome
``OfficeActorOutcome``.

Modules, lowest layer first (no module imports one above it — W0-G6):

==========  ======  ============================================================
module      layer   owns
==========  ======  ============================================================
models      models  scans, typed outcomes, the position-policy hook, the caps
normalize   stores  write-time payload normalization and display-name checks
files       stores  surface / actor / sidecar writes and the actor-dir read
store       stores  ``OfficeStore`` (its module docstring holds the invariants)
==========  ======  ============================================================

Stores written: ``paths.office_dir(workspace)`` — the surface file, one JSON file
per actor, ``archive/`` and the conflict sidecars — and the event log.

Every name an importer takes from ``agent_runtime.office_store`` today is
re-exported below, so no importer changes with the package.
"""

from __future__ import annotations

from agent_runtime.office_store.models import (
    ActorScan,
    ARCHIVED_LEDGER_CAP,
    ConflictScan,
    MAX_FOLDERS,
    MAX_ITEMS_PER_ACTOR,
    MAX_UNREADABLE_ACTOR_FILE_NAMES,
    merge_archived_ledgers,
    NO_UNREADABLE_ACTOR_FILES,
    OfficeActorOutcome,
    OfficePositionPolicy,
    OUTCOME_OK,
    UnreadableActorFiles,
)

from agent_runtime.office_store.normalize import (
    _assert_display_name_publishable,
    _normalize_persona_id,
)

from agent_runtime.office_store.files import (
    read_actor_dir,
    _read_json,
    _write_actor,
    _write_surface,
)

from agent_runtime.office_store.store import (
    OfficeStore,
)

__layer__ = "stores"

__all__ = [
    "ActorScan",
    "ARCHIVED_LEDGER_CAP",
    "ConflictScan",
    "MAX_FOLDERS",
    "MAX_ITEMS_PER_ACTOR",
    "MAX_UNREADABLE_ACTOR_FILE_NAMES",
    "merge_archived_ledgers",
    "NO_UNREADABLE_ACTOR_FILES",
    "OfficeActorOutcome",
    "OfficePositionPolicy",
    "OfficeStore",
    "OUTCOME_OK",
    "read_actor_dir",
    "UnreadableActorFiles",
    "_assert_display_name_publishable",
    "_normalize_persona_id",
    "_read_json",
    "_write_actor",
    "_write_surface",
]
