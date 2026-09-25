"""The resurrection-guard ledgers: how two members' realm JSON ledgers merge on pull.

Pure policy over rows (RD-11): the skill-tombstone and workspace-lift registers
merge newest-transition-wins, the deleted-workspace ids as a set union minus live
lifts; plus the ledger's receipt rows for the status envelope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Realm
from ..store import (
    DELETED_WORKSPACE_LEDGER_CAP,
    SKILL_TOMBSTONE_LEDGER_CAP,
    active_skill_tombstones,
    # One body, this lane's spelling. The definition lives in `store` (its
    # docstring says why); the local name stays because every call site below
    # reads as a ledger-merge step, and one of them is a mutation claim's
    # needle in `tests/mutation_claims.json`.
    ledger_time as _ledger_time,
    prune_settled_ledger,
    workspace_lift_is_active,
)

__layer__ = "policy"
__all__ = [
    "_REALM_AUTHORITY_FIELDS",
    "_UNIONED_REALM_LEDGERS",
    "_newer_tombstone_row",
    "_skill_tombstone_rows",
    "_tombstone_transition_at",
    "merge_deleted_workspace_ledgers",
    "merge_skill_tombstone_ledgers",
    "merge_workspace_lift_ledgers",
    "skill_tombstone_rows",
]


def skill_tombstone_rows(realm: Realm) -> list[dict[str, Any]]:
    """The ledger as receipt rows for the status envelope and the sidecar.

    Public because ``hermes harness realm skills show`` renders the SAME rows
    (plan §4): a second rendering in the CLI is how one ledger ends up with two
    receipt shapes that drift.

    ACTIVE entries only, and the row shape is unchanged by RD-11: the register's
    restored entries are bookkeeping the merge needs, not deletes an operator
    can act on, and a "deleted from realm" sheet that listed them would offer a
    restore affordance for a skill that is not blocked.
    """

    return [
        {
            "slug": entry.slug,
            "deleted_at": entry.deleted_at.astimezone(timezone.utc).isoformat(),
            "deleted_hash": entry.deleted_hash,
        }
        for entry in sorted(active_skill_tombstones(realm), key=lambda item: item.slug)
    ]


#: Historical private name, kept for this module's own call sites.
_skill_tombstone_rows = skill_tombstone_rows


#: Fields a server-bound realm owns from backend adoption. An older repo
#: snapshot must never roll one of these back.
_REALM_AUTHORITY_FIELDS = (
    "id",
    "name",
    "slug",
    "server_id",
    "default_workspace_id",
    "default_workspace_name",
    "default_workspace_version",
    "sync_manifest_ref",
)

#: The realm-JSON lists that are RESURRECTION-GUARD LEDGERS rather than realm
#: truth, and so are UNIONED on pull instead of last-writer-wins-adopted
#: (RD-11). Each names its merge, and each is keyed and bounded by its own rule.
#: Every other realm field keeps the LWW posture ``skill_selection`` documents.
#:
#: ORDER IS LOAD-BEARING: ``workspace_lifts`` is merged before
#: ``deleted_workspace_ids`` because the deleted-id union SUBTRACTS the ids the
#: merged lift register says are live (w13/h2).
_UNIONED_REALM_LEDGERS = ("skill_tombstones", "workspace_lifts", "deleted_workspace_ids")


def _tombstone_transition_at(row: dict[str, Any]) -> "datetime | None":
    """When this entry last CHANGED STATE — the union merge's comparison key.

    Not ``deleted_at``: after RD-11 an entry is a per-slug state register, and a
    restore is a NEWER fact about the same ``deleted_at``. Ranking by the later
    of the two stamps is what makes "restore beats a stale delete" and "a fresh
    re-delete beats an older restore" the same comparison rather than two rules.
    """

    stamps = [
        stamp
        for stamp in (_ledger_time(row.get("restored_at")), _ledger_time(row.get("deleted_at")))
        if stamp is not None
    ]
    return max(stamps) if stamps else None


def _newer_tombstone_row(held: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Pick the entry that describes the more recent state of one slug.

    ``held`` is seeded from the LOCAL ledger, so every tie resolves to this
    member's own record. Two ties are decided deliberately:

    - An entry whose stamps do not parse cannot out-rank one that has a
      readable stamp; it only wins when nothing else is readable either.
    - Equal transition times with DIFFERENT states resolve to the DELETE. This
      ledger exists to stop a silent resurrection; a restore that loses a
      microsecond tie is one explicit verb away from being re-run, while a
      block that loses one is a deleted skill quietly publishable again.
    """

    held_at = _tombstone_transition_at(held)
    candidate_at = _tombstone_transition_at(candidate)
    if candidate_at is None:
        return held
    if held_at is None or candidate_at > held_at:
        return candidate
    if candidate_at < held_at:
        return held
    held_blocks = _ledger_time(held.get("restored_at")) is None
    candidate_blocks = _ledger_time(candidate.get("restored_at")) is None
    if candidate_blocks and not held_blocks:
        return candidate
    return held


def merge_skill_tombstone_ledgers(
    local: Any, incoming: Any
) -> list[dict[str, Any]]:
    """Per-slug newest-transition-wins UNION of two skill-tombstone ledgers.

    The gap this closes (RD-11, upgrading R-D from "LWW acceptable"): the realm
    JSON used to be adopted wholesale on pull, so two members publishing
    concurrently silently dropped each other's tombstone entries and a deleted
    skill became publishable again. A union cannot drop an entry — the worst a
    concurrent publish can now do is delay one.

    Keyed on the EXACT slug, because that is the key ``tombstone_skill`` dedupes
    on; the bare-name-covers-categorized rule is a MATCH rule
    (``store.skill_tombstoned``) and applying it here would silently fold two
    distinct entries into one. Rows that are not dicts, or carry no usable slug,
    are dropped: ``skill_tombstoned`` reads ``entry.slug``, so such a row blocks
    nothing, and carrying it forward only risks breaking the next realm load.

    Output is oldest-transition-first (the append order every ledger chokepoint
    keeps) and bounded by the shared settled-first rule.
    """

    merged: dict[str, dict[str, Any]] = {}
    for rows in (local, incoming):
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            held = merged.get(slug)
            merged[slug] = dict(row) if held is None else _newer_tombstone_row(held, dict(row))
    ordered = sorted(
        merged.values(),
        key=lambda row: (
            _tombstone_transition_at(row) or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("slug") or ""),
        ),
    )
    return prune_settled_ledger(
        ordered,
        cap=SKILL_TOMBSTONE_LEDGER_CAP,
        settled=lambda row: _ledger_time(row.get("restored_at")) is not None,
    )


def merge_workspace_lift_ledgers(local: Any, incoming: Any) -> list[dict[str, Any]]:
    """Per-workspace newest-transition-wins UNION of two lift registers.

    The propagating half of a workspace-delete lift (RULED 2026-09-04; see
    :class:`models.WorkspaceLift` for why a bare removal could not travel). The
    comparison is the SKILL ledger's, reused rather than restated — both are
    per-key state registers over the same ``restored_at``/``deleted_at`` pair,
    and the tie rule (equal stamps resolve to the DELETE) has to be the same in
    both or the two ledgers disagree about the same instant.

    Rows that are not dicts, or carry no ``workspace_id``, are dropped: nothing
    downstream can key on them, and carrying one forward only risks breaking the
    next realm load.

    Output is oldest-transition-first and bounded SUPERSEDED-FIRST — a marker a
    re-delete has already superseded is settled history whose id is back on
    ``deleted_workspace_ids`` anyway, while evicting a LIVE lift would re-delete
    a live workspace.
    """

    merged: dict[str, dict[str, Any]] = {}
    for rows in (local, incoming):
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            workspace_id = str(row.get("workspace_id") or "").strip()
            if not workspace_id:
                continue
            held = merged.get(workspace_id)
            merged[workspace_id] = (
                dict(row) if held is None else _newer_tombstone_row(held, dict(row))
            )
    ordered = sorted(
        merged.values(),
        key=lambda row: (
            _tombstone_transition_at(row) or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("workspace_id") or ""),
        ),
    )
    return prune_settled_ledger(
        ordered,
        cap=DELETED_WORKSPACE_LEDGER_CAP,
        settled=lambda row: not workspace_lift_is_active(row),
    )


def merge_deleted_workspace_ledgers(
    local: Any, incoming: Any, *, lifts: Any = None
) -> list[str]:
    """Set-union of two ``deleted_workspace_ids`` ledgers, MINUS the live lifts.

    The union half is unchanged and stays a plain set union with no state
    register of its own: these are freshly-minted ids, never re-creatable names,
    so an id that stays on the ledger forever can never block a legitimate
    re-creation (``models`` :class:`SkillTombstone` spells the asymmetry out).

    MEASURED BOUNDARY (2026-08-31, W2-H5), and what closed it. The plan called
    the union safe because the ledger has "no restore verb", and that is not
    literally true — ``default_scope.ensure_default_scope`` and the fixed-id
    reconcile path both LIFT an id when the reserved local-default workspace
    turns up on the ledger. Under LWW a lift travelled on the next publish;
    under a union a removal is an ABSENCE, which the merge cannot tell apart
    from "that peer never heard about this delete", so the lift stayed local
    until the id aged out of the cap.

    ``lifts`` is the merged lift register (:func:`merge_workspace_lift_ledgers`)
    and it is what makes the lift travel: an id whose marker is still live is
    subtracted from the union, so a peer that has not yet seen the restore
    cannot re-add it. Absent or empty ``lifts`` reproduces the pre-2026-09-04
    behaviour EXACTLY, which is what an old member's realm JSON gets.
    """

    live_lifts = {
        str(row.get("workspace_id") or "").strip()
        for row in (lifts if isinstance(lifts, list) else [])
        if isinstance(row, dict) and workspace_lift_is_active(row)
    }
    live_lifts.discard("")
    merged: list[str] = []
    seen: set[str] = set()
    for rows in (local, incoming):
        for raw in rows if isinstance(rows, list) else []:
            value = str(raw or "").strip()
            if not value or value in seen or value in live_lifts:
                continue
            seen.add(value)
            merged.append(value)
    return merged[-DELETED_WORKSPACE_LEDGER_CAP:]
