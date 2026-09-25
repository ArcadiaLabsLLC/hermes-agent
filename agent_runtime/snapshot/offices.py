"""The offices projection: actor rows, the office summary, and office parity
warnings.
"""

from __future__ import annotations

from typing import NamedTuple

from agent_runtime.office_models import (
    ORPHANED_OFFICE_REASON_UNKNOWN,
    ORPHANED_OFFICE_WORKSPACE_DELETED,
    ORPHANED_OFFICE_WORKSPACE_NEVER_RECORDED,
)
from agent_runtime.office_models import MAX_OFFICE_ACTORS_PROJECTED
from agent_runtime.serde import section_rows, to_jsonable

__layer__ = "stores"

__all__ = [
    "MAX_OFFICE_ACTORS_PROJECTED",
    "OfficesProjection",
    "_ORPHANED_OFFICE_DETAIL",
    "office_actor_summary_row",
    "_office_parity_warnings",
    "_offices_summary",
    "office_summary_row",
]



def office_actor_summary_row(actor, *, unpublished: bool | None) -> dict:
    row = {
        "actor_key": actor.actor_key,
        "persona_id": actor.persona_id,
        "persona_instance_id": actor.persona_instance_id,
        "backing_profile": actor.backing_profile,
        "items": [
            {
                "item_id": item.item_id,
                "persona_id": item.persona_id,
                "kind": item.kind,
                "position": list(item.position),
                "folder": item.folder,
                "display_name": item.display_name,
                "pet_slug": item.pet_slug,
                "scale": item.scale,
            }
            for item in actor.items
        ],
        "revision": actor.revision,
        "updated_at": to_jsonable(actor.updated_at),
        "updated_by": actor.updated_by,
    }
    if unpublished is not None:
        row["unpublished"] = unpublished
    return row


def office_summary_row(
    surface,
    actors,
    *,
    actors_unreadable: int,
    conflict_actor_keys=(),
    conflict_guessed_keys,
    actor_unpublished=None,
    orphaned: bool = False,
    orphan_reason: str | None = None,
) -> dict:
    """ONE Mission Office surface projection row — the single authority for the
    actor projection bound and its truncation accounting.

    Extracted from ``_offices_summary``'s loop body verbatim (S48, ledger item
    4), same reason as :func:`board_summary_row`: the ``hermes harness office``
    CLI tier rendered its own uncapped actor list. ``actors`` and
    ``conflict_actor_keys`` are the caller's already-fetched store reads.

    ``actors_unreadable`` is REQUIRED, and required by keyword, because this row
    had exactly the defect RD-H4 / EG-1.5 fixed one seam over in
    ``serve_rpc._office_projection``: ``office_store.read_actor_dir`` skips a
    file it cannot decode and returns the rest, so ``actors`` arrives already
    SHORTENED, and computing ``actors_truncated`` from that shortened length
    answers 0. A launcher rendering that row cannot tell a desk that was removed
    from a desk whose file the platform would not open. Both production callers
    now read through the ``scan_actors`` chokepoint and state the count; a caller
    that genuinely holds a bare list has to say ``actors_unreadable=0`` out loud
    rather than get it by default, which is the same "never silently zero" rule
    ``ActorScan.unreadable`` is declared under.

    ``conflict_guessed_keys`` is REQUIRED by keyword under that same rule, and
    for the conflict list's version of the same defect (RD-5): a conflict
    sidecar that will not decode — or one that decodes and does not name its
    actor — still contributes a key, but the key is
    ``office_models.actor_file_token(actor_key)``, sanitised and truncated at 64
    characters with a hash suffix. For a long key it is NOT the actor key, so
    ``office resolve-conflict --actor <it>`` finds nothing, and both readers of
    this row present these to an operator as keys to act on. The subset that is
    a guess rides the ROW rather than being re-derived at each reader, for the
    reason ``orphan_reason`` does: one scan decides it, and a second derivation
    with its own inputs is free to disagree with the list it explains. A caller
    with no conflicts still says ``conflict_guessed_keys=()`` out loud rather
    than getting "none of these are guesses" by default.

    This matters twice over for the persisted core (EG-3.1): a core is written
    back after every build, so a projection that under-reported its own
    completeness would be persisted as fingerprint-blessed truth and served to
    every later boot.
    """

    projected = actors[:MAX_OFFICE_ACTORS_PROJECTED]
    return {
        "workspace_id": surface.workspace_id,
        "folders": list(surface.folders),
        "actors": [
            office_actor_summary_row(a, unpublished=(actor_unpublished(a) if actor_unpublished is not None else None))
            for a in projected
        ],
        "actor_count": len(actors),
        "actors_truncated": max(0, len(actors) - len(projected)),
        # The OTHER way this list can be short, and the one it used to hide
        # completely: files that exist and would not decode. Its sibling above
        # counts a cut WE chose; this one counts rows the platform took.
        # Additive — an old launcher ignores the key.
        "actors_unreadable": int(actors_unreadable),
        "conflict_actor_keys": list(conflict_actor_keys),
        # WHICH of those keys the scan had to GUESS from a filename. Additive —
        # an old launcher ignores the key, and a row from an older core has no
        # such list, which reads as the claim the bare list used to make
        # silently: every key came out of a payload.
        "conflict_guessed_keys": list(conflict_guessed_keys),
        "archived_actor_keys": list(surface.archived_actor_keys),
        "revision": surface.revision,
        "updated_at": to_jsonable(surface.updated_at),
        # A surface whose workspace does not resolve is accounted, never
        # silently hidden — parity warning below.
        "orphaned": orphaned,
        # WHICH KIND of orphan, from ``office_models``' typed vocabulary, or
        # ``None`` when the surface is not orphaned at all. It rides the ROW
        # rather than being recomputed at the warning because ``orphaned`` is
        # decided here, from one workspace enumeration, and ``workspace_resolves``
        # exists precisely so this predicate and the ``orphaned_office`` warning
        # "cannot answer differently". A reason derived at the warning would be a
        # second derivation with its own inputs — free to drift from the flag it
        # is supposed to be explaining. Additive: an old launcher ignores the key.
        "orphan_reason": orphan_reason,
    }


class OfficesProjection(NamedTuple):
    """The office rows this snapshot BUILT, beside how many whole workspaces it
    could not build a row for.

    Same two-fields-or-nothing law as ``ActorScan`` one layer down, and for the
    same reason: ``_offices_summary`` skipped a workspace whose ``get_surface``
    threw, so that office simply was not in the snapshot — indistinguishable
    from a workspace that has no office at all. ``actors_unreadable`` made the
    count honest INSIDE a row (EG-1.5); the row that never existed was the gap
    left over. It matters twice for the persisted core: a core is written back
    after every build, so an under-reported projection is persisted as
    fingerprint-blessed truth and served to every later boot.
    """

    offices: list[dict]
    #: Workspaces whose office surface would not decode. Additive on the wire as
    #: ``offices_unreadable`` — an old launcher ignores the key.
    unreadable: int


def _offices_summary(office_store, workspaces, realms=()) -> OfficesProjection:
    """Mission Office projection rows, keyed by workspace_id. Local reads only:
    conflict state from local sidecar files, ``unpublished`` from the local
    realm-sync baseline sidecar (a pure file read — Decision 7 posture).

    ``realms`` are the realm rows the caller has ALREADY read, supplied only so
    an orphaned row can say WHICH KIND of orphan it is (their bounded
    ``deleted_workspace_ids`` ledgers are the discriminator). Nothing here reads
    the realm store: a second enumeration would be free to disagree with the
    workspace set that decided ``orphaned`` on the line above it, which is the
    exact divergence ``OfficeStore.workspace_resolves``' docstring exists to
    forbid. Defaulted so the CLI tier's callers are unaffected — with no realms
    the classifier answers ``unknown``, which is the honest reading of "no ledger
    could have recorded anything", not a silent downgrade.
    """

    from ..office_models import classify_orphaned_office_workspace
    from ..office_sync import read_office_baseline
    from ..store import DELETED_WORKSPACE_LEDGER_CAP

    workspace_ids = {getattr(w, "id", None) for w in workspaces}
    deleted_ledgers = [
        list(getattr(realm, "deleted_workspace_ids", None) or []) for realm in (realms or ())
    ]
    realm_by_workspace = {getattr(w, "id", None): getattr(w, "realm_id", None) for w in workspaces}
    baselines: dict[str, dict[str, str]] = {}
    offices: list[dict] = []
    unreadable = 0
    for workspace_token in office_store.list_workspaces():
        try:
            surface = office_store.get_surface(workspace_token)
        except Exception:
            # COUNTED, never vanished. The workspace id lives inside the file
            # that would not parse, so no row can be built for it — but its
            # absence from ``offices`` may not be the only trace it leaves.
            unreadable += 1
            continue
        # ``scan.unreadable`` reaches the row below rather than being dropped:
        # the rows alone lose the files that would not decode, and the row must
        # not describe itself as complete when it is not. Same chokepoint the
        # RPC office projection reads through, so ``runtime.office.get`` and the
        # snapshot cannot disagree about how complete the office they just
        # handed over was.
        scan = office_store.scan_actors(workspace_token)
        actors = scan.actors
        realm_id = realm_by_workspace.get(surface.workspace_id)
        baseline: dict[str, str] | None = None
        if realm_id:
            if realm_id not in baselines:
                try:
                    baselines[realm_id] = read_office_baseline(realm_id)
                except Exception:
                    baselines[realm_id] = {}
            baseline = baselines[realm_id]

        def _actor_unpublished(actor) -> bool | None:
            # Publication honesty is only meaningful for realm-bound workspaces.
            if baseline is None:
                return None
            from ..office_models import office_content_hash

            return baseline.get(f"{surface.workspace_id}:actor:{actor.actor_key}") != office_content_hash(actor)

        orphaned = surface.workspace_id not in workspace_ids
        # ONE scan, both lists. ``scan_conflicts`` knows which of these keys came
        # from a sidecar that would not decode (a filename token, not an actor
        # key) and which were read out of a payload; taking ``.keys`` here and
        # re-deriving the guesses at the warning would be two reads of one
        # directory, free to disagree between the row and the sentence that
        # explains it. The row carries both (RD-5).
        conflicts = office_store.scan_conflicts(workspace_token)
        offices.append(
            office_summary_row(
                surface,
                actors,
                actors_unreadable=scan.unreadable,
                conflict_actor_keys=conflicts.keys,
                conflict_guessed_keys=conflicts.guessed_keys,
                actor_unpublished=_actor_unpublished,
                orphaned=orphaned,
                orphan_reason=(
                    classify_orphaned_office_workspace(
                        surface.workspace_id,
                        deleted_ledgers=deleted_ledgers,
                        ledger_cap=DELETED_WORKSPACE_LEDGER_CAP,
                    )
                    if orphaned
                    else None
                ),
            )
        )
    return OfficesProjection(offices=offices, unreadable=unreadable)


#: Detail wording per orphan reason. One sentence each, and each says something
#: an operator can ACT on differently — the whole reason the reason exists. The
#: old single wording ("which no longer resolves") presumed a deletion for every
#: orphan and sent the reader hunting one that, in the live field case, had never
#: happened.
_ORPHANED_OFFICE_DETAIL = {
    ORPHANED_OFFICE_WORKSPACE_DELETED: (
        "its workspace record was deleted (a realm still holds the tombstone)"
    ),
    ORPHANED_OFFICE_WORKSPACE_NEVER_RECORDED: (
        "no workspace record was ever created for it"
    ),
    ORPHANED_OFFICE_REASON_UNKNOWN: (
        "the realm deletion ledgers cannot say whether it was deleted or never recorded"
    ),
}


def _office_parity_warnings(data) -> list[dict]:
    warnings: list[dict] = []
    for office in section_rows(data.get("offices")):
        if office.get("orphaned"):
            # The row decided BOTH ``orphaned`` and its reason, from one
            # workspace enumeration. A row from an older core (or a caller that
            # built the row without realms) carries no reason; ``unknown`` is the
            # honest reading of that, and it is the one value here that never
            # claims to know something.
            reason = str(office.get("orphan_reason") or "").strip() or ORPHANED_OFFICE_REASON_UNKNOWN
            explanation = _ORPHANED_OFFICE_DETAIL.get(
                reason, _ORPHANED_OFFICE_DETAIL[ORPHANED_OFFICE_REASON_UNKNOWN]
            )
            warnings.append(
                {
                    # UNCHANGED, deliberately. The code is what a census greps
                    # and what the launcher's ``warningCodes`` reads; carrying
                    # the reason in the token (``orphaned_office_deleted``, …)
                    # would zero every existing count of this condition. One
                    # token, discrimination in a FIELD.
                    "code": "orphaned_office",
                    "entity_id": office.get("workspace_id"),
                    "reason": reason,
                    "detail": (
                        f"office surface points at workspace '{office.get('workspace_id')}', "
                        f"which no workspace record resolves: {explanation}. Archive it "
                        "with `harness office archive-surface --workspace "
                        f"{office.get('workspace_id')}`"
                    ),
                }
            )
        # WHICH of the conflict keys below the scan had to guess from a
        # filename (RD-5). Decided by the row, from the one ``scan_conflicts``
        # that produced the keys — see ``office_summary_row``. Absent on a row
        # from an older core, and an empty set is then the honest reading: this
        # builder cannot know, and every key is presented the way the bare list
        # always presented it.
        guessed = set(office.get("conflict_guessed_keys") or ())
        for actor_key in office.get("conflict_actor_keys") or []:
            is_guess = actor_key in guessed
            warnings.append(
                {
                    "code": "office_actor_conflict",
                    "entity_id": actor_key,
                    "workspace_id": office.get("workspace_id"),
                    # The code stays ONE token (the ``orphaned_office`` rule:
                    # discrimination in a FIELD, never in the code, or every
                    # existing census of this condition zeroes). This is the
                    # field, and it is what a program branches on; the sentence
                    # below is for the human reading the console.
                    "guessed": is_guess,
                    "detail": (
                        f"office actor '{actor_key}' has an unresolved realm-sync conflict; "
                        "resolve with `harness office resolve-conflict --actor <key> --take local|remote`"
                        + (
                            " (filename guess — resolve-conflict will not find this key)"
                            if is_guess
                            else ""
                        )
                    ),
                }
            )
    return warnings
