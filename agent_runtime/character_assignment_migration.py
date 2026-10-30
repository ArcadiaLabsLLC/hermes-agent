"""Conservative startup migration of verified, exact-instance assignments.

Only identical explicit choices on every stored placement move automatically.
Local fallback maps have no account/runtime provenance, so inherited, ambiguous
and malformed choices stay intact until an explicit character command. This is
a migration adapter, not another assignment store or renderer service.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import ExitStack

from hermes_time import now

from .character_assignment import CharacterAssignmentChange, CharacterAssignmentRefused
from .character_assignment_legacy import character_migration_choice, character_source_fingerprint, office_character_migration_sources
from .locks import character_legacy_assignment_lock
from .persona_assignments.store import PersonaInstanceStore

__layer__ = "stores"


def migrate_authored_character_assignments() -> dict:
    store = PersonaInstanceStore()
    scan = store.scan_all()
    if scan.unreadable:
        return {"migrated": [], "retained": {}, "error": "instance_inventory_unreadable"}
    pending = sorted((row for row in scan.instances if row.character_assignment is None), key=lambda row: row.id)
    result = {"migrated": [], "retained": {}}
    if not pending:
        return result
    # Lock only the unmigrated subjects, in stable order, before scanning once.
    # An old office writer cannot add a conflicting placement between inventory
    # and cutover, even in a workspace created during this migration.
    with ExitStack() as locks:
        for row in pending:
            locks.enter_context(character_legacy_assignment_lock(row.id, row.persona_id))
        by_instance = defaultdict(list)
        for source in office_character_migration_sources():
            by_instance[(source["instance_id"], source["persona_id"])].append(source)
        for row in pending:
            if store.get(row.id).character_assignment is not None:
                continue
            sources = by_instance[(row.id, row.persona_id)]
            if not sources:
                result["retained"][row.id] = "legacy_inheritance"
                continue
            try:
                mode, asset = character_migration_choice(sources, persona=False)
            except CharacterAssignmentRefused as exc:
                result["retained"][row.id] = exc.reason.value
                continue
            fingerprint = character_source_fingerprint(sources)
            receipt = {"version": 1, "sources": sources, "source_fingerprint": fingerprint, "migrated_at": now().isoformat()}
            store.set_character_assignment(row.id, CharacterAssignmentChange(
                0, mode, asset, f"migration-v1-{fingerprint}", receipt,
            ))
            result["migrated"].append(row.id)
    return result
