"""The office store package — the package map (program rule 16).

Entry points (what calls in): ``OfficeStore`` (the single write chokepoint for
the Mission Office domain — every office verb, the office RPC lane, realm sync
and the snapshot builder), ``read_actor_dir`` / ``ActorScan`` (the actor
directory read ``office_sync`` takes), and the typed outcome
``OfficeActorOutcome`` — the reference for typed store outcomes (rule 14).

The store is COMPOSED: ``store`` holds the reads, the event append and the
class, and each lane module holds one verb family as functions over the store,
bound onto the class as methods (``OfficeStore.upsert_actor is
actor_writes.upsert_actor``), so every caller — and every test patching a class
attribute — sees the class it always saw. The invariants the store upholds are
``store``'s module docstring.

Modules, lowest layer first (no module imports one above it — W0-G6):

==============  ======  ========================================================
module          layer   owns
==============  ======  ========================================================
models          models  scans, typed outcomes, the position-policy hook, caps
normalize       policy  write-time payload normalization, display-name checks
files           stores  THE file writes (surface, live actor, archived actor)
patches         stores  the ``state.patched`` producers
guards          stores  the tombstone and class-key fences
surface_writes  stores  ensure / update a surface
conflicts       stores  scan and resolve sync conflicts; the conflict guard
actor_writes    stores  ``ActorUpsert``; upsert / remove / restore an actor
adoption        stores  adopt a peer's surface or actor (realm sync)
archive         stores  orphaned surfaces, a retired instance's actors
store           stores  ``OfficeStore``: reads, events, lane bindings
==============  ======  ========================================================

Shared owners this package spends: ``agent_runtime.store_events`` (the event
append), ``agent_runtime.store_conflicts`` (sidecars, the revision check),
``agent_runtime.serde.read_json``.

Stores written: ``paths.office_dir(workspace)`` — the surface file, one JSON file
per actor, ``archive/`` and the conflict sidecars — and the event log.

Every name an importer takes from ``agent_runtime.office_store`` is re-exported
below, so no importer changes with the package.
"""

from __future__ import annotations

from agent_runtime.office_store.models import (
    ActorScan,
    ARCHIVED_LEDGER_CAP,
    ConflictScan,
    MAX_FOLDERS,
    MAX_ITEMS_PER_ACTOR,
    MAX_UNREADABLE_ACTOR_FILE_NAMES,
    NO_UNREADABLE_ACTOR_FILES,
    OfficeActorOutcome,
    OfficePositionPolicy,
    OUTCOME_OK,
    UnreadableActorFiles,
)

from agent_runtime.office_store.normalize import (
    _assert_display_name_publishable,
)

from agent_runtime.office_store.files import (
    read_actor_dir,
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
    "NO_UNREADABLE_ACTOR_FILES",
    "OfficeActorOutcome",
    "OfficePositionPolicy",
    "OfficeStore",
    "OUTCOME_OK",
    "read_actor_dir",
    "UnreadableActorFiles",
    "_assert_display_name_publishable",
    "_write_actor",
    "_write_surface",
]
