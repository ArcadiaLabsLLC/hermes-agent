"""The roster/office placement census: the orphan and duplicate classifiers, the per-workspace sweeps, the report.

Map: ``agent_runtime/harness_doctor/__init__.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .model import HEALTH_DEFECT, HEALTH_NOTICE, HEALTH_OK, HEALTH_UNKNOWN, _DoctorProbeContext, _error_text

__layer__ = "lanes"


# -- the roster/office join, as a READ (plan D1/D8) ---------------------------
#
# Two stores answer two different questions and neither is folded into the
# other: the persona-instance row answers "does this agent exist" (the
# roster-only recovery door ``persona instance create --add-instance``
# legitimately mints rows that were never placed), and the instance-keyed
# office actor answers "is it on this level". Nothing had ever looked at the
# JOIN — ``harness doctor`` reported six sections and none of them was this
# one, and ``persona instance reconcile`` prunes orphan ROWS without ever
# opening the office. So a half-state (a retired instance whose actor survived,
# a placement whose compensation archived the row and not the desk) was
# representable, durable, and invisible to the tool an operator runs to find it.
#
# This section is a READ and only a read. The repairs already exist and are
# deliberate operator gestures — a retire for an orphan actor, a resumed create
# for an unplaced row — so a doctor that silently reconciled them would be
# choosing which of the two stores was wrong on the operator's behalf, on
# evidence it can only see one snapshot of.


def _census_instance_key(raw_id: Any, *, persona_id: Any = None) -> str:
    """The one spelling BOTH sides of the join are compared in.

    ``OfficeStore.upsert_actor`` stores ``persona_instance_id`` through
    ``canonical_persona_instance_id`` (via ``_canonical_actor_key``), so a
    roster row still carrying a legacy spelling would read as an orphan against
    its own actor if the two sides were compared raw. Routing BOTH sides through
    the single derivation authority is what keeps this census from inventing
    findings out of the id drift that ``persona instance reconcile`` exists to
    fold.

    **Both sides means both.** Until H-H11 only the roster side was routed
    through here, and the actor side was read raw off the file — which is not
    the same set of ids, because ``upsert_actor`` is not the only writer: the
    realm pull's ``adopt_remote_actor`` writes a PEER's row verbatim, legacy
    spelling and all, and that actor then reported as an ``orphan_actor``
    against a roster row it names correctly. A defect invented out of a
    spelling, in the section whose whole contract is not to do that.

    ``""`` for an id that is absent or unreadable — a class-keyed actor, which
    is out of the join by construction rather than by omission.
    """

    from ..persona_assignments import canonical_persona_instance_id

    raw = str(raw_id or "").strip()
    if not raw:
        return ""
    canonical = canonical_persona_instance_id(raw, persona_id=persona_id)
    return canonical or raw


def _census_unknown(detail: str, *, unreadable: list[str] | None = None) -> dict[str, Any]:
    """The census as UNEXAMINED. Every count is ``None``, never ``0``/``[]``.

    A store this section could not read leaves it with no world to count, and an
    empty list here would read to an operator as "looked, found none" — the
    false all-clear the whole doctor is written against.

    A SHORT world takes this path too, and that is the subtle half. Both scans
    return the rows they could read beside a count of the ones they could not
    (``PersonaInstanceScan`` / ``ActorScan`` carry that count for exactly this
    reason). A census that partitioned the readable remainder would report a
    perfectly healthy placement as an ORPHAN — because the file that would not
    decode is its roster row — inventing a defect out of an outage and pointing
    the operator's remediation at the wrong store. So a partition is computed
    only over a world that was read in full.
    """

    report: dict[str, Any] = {
        "health": HEALTH_UNKNOWN,
        "error": detail,
        "observed": False,
        "placed": None,
        "unplaced_rows": None,
        "orphan_actors": None,
        # Same rule again, and for a reason of its own: "no OTHER live actor
        # holds this id" is the absence a duplicate sweep asserts, and a file
        # that would not open is one that might be holding it.
        "duplicate_placements": None,
        "workspaces": None,
    }
    if unreadable:
        report["unreadable"] = sorted(unreadable)
    return report


# The DESK-LITTER CENSUS stood here (plan DL-H1) — four ``DESK_LITTER_*``
# reasons, the pure ``_desk_litter_reason`` classifier that filed a live
# ``kind: "desk"`` item into one of them, and the ``_census_desk_litter`` /
# ``_census_agent_item_bindings`` sweeps below that fed it. All retired
# 2026-09-18 by owner ruling: *"i want desks to just be one type all agents can
# use, no more per persona desk, just one single desk object."*
#
# Every one of the four reasons was a statement about a desk's AGENT HALF —
# missing, scope-stale, persona-retired, or never a desk at all. A generic desk
# has no agent half by construction: its ``persona_id`` is its own synthetic id
# (``desk_<8 base36>``), so no ``kind: "agent"`` item will ever share it and
# ``agent_missing`` would have fired on every correctly-placed desk, forever. A
# notice an operator cannot clear is a notice they stop reading, which is the
# failure this whole doctor is written against — so the class goes rather than
# being re-keyed. The plan is
# ``EterniaLauncher/docs/mission_control/planned/generic-desk-and-inspector-tables.md``
# (slice 1).
#
# What KEPT its place, because none of it was about desks: ``orphan_actors``
# (an ACTOR whose instance is retired or missing — kind-agnostic),
# ``unplaced_rows``, and ``duplicate_placements`` (one item id held by two live
# actor rows, which is a claim about ROWS and fires on any kind).


#: The retire that archived this actor's roster row RECORDED that it could not
#: archive this actor (H-H5's receipt names the key). This is the "row archived,
#: desk still live" half-state the retire ack has reported since S5 and nothing
#: could see afterwards — the ack was the only witness and it expired with the
#: call. The repair is a re-retire (the replay sweeps live placements, D2) or
#: ``runtime.office.remove``.
ORPHAN_ACTOR_RETIRE_INCOMPLETE = "retire_incomplete"

#: This install holds a retirement tombstone for the instance and its receipt
#: does NOT name this actor — so the actor was placed after the retire, or the
#: receipt is from before H-H5 and cannot say. Softer than
#: ``retire_incomplete`` on purpose: an unreadable or absent receipt degrades to
#: here, and both reasons share a repair set.
ORPHAN_ACTOR_INSTANCE_RETIRED = "instance_retired"

#: No tombstone and no live row: this install has never held the instance. The
#: realm-pulled placement (office actors sync, persona instances are per-install
#: by ruling), for which `agent retire` is the refusal arm by construction and
#: ``runtime.office.remove`` is the only verb that works.
ORPHAN_ACTOR_INSTANCE_UNKNOWN = "instance_unknown"

ORPHAN_ACTOR_REASONS = (
    ORPHAN_ACTOR_RETIRE_INCOMPLETE,
    ORPHAN_ACTOR_INSTANCE_RETIRED,
    ORPHAN_ACTOR_INSTANCE_UNKNOWN,
)


def _orphan_actor_reason(
    *,
    actor_key: str,
    instance_id: str,
    retired: frozenset[str],
    receipt: dict[str, Any] | None,
) -> str:
    """Which of the three orphans this actor is (H-H4).

    Pure — the tombstone set and the receipt are both read by the caller, once
    each, so the partition is unit-testable without a filesystem fixture.

    The census has reported ``orphan_actors`` as one undifferentiated bucket
    since S6, and the doctor's remediation string has had to describe the split
    in PROSE ("an orphan actor whose instance this install still holds … one
    whose instance this install never held …") because there was no field to key
    it on. There is now, and it is keyed on facts the store holds — a tombstone,
    and a receipt naming this actor key — never on an id's shape.

    ``retire_incomplete`` first, because it is the narrowest: an actor named by
    its own retire's failure list is retired AND unarchived, and reporting it as
    merely ``instance_retired`` would lose the one fact that says a retry is the
    repair. A receipt that is absent or unreadable degrades to
    ``instance_retired``, which is the safe direction — same row, same count,
    the softer of two statements about the same absence.
    """

    if instance_id not in retired:
        return ORPHAN_ACTOR_INSTANCE_UNKNOWN
    failures = (receipt or {}).get("office_archive_failures") or []
    if isinstance(failures, list) and any(
        isinstance(failure, dict) and str(failure.get("actor_key") or "") == actor_key
        for failure in failures
    ):
        return ORPHAN_ACTOR_RETIRE_INCOMPLETE
    return ORPHAN_ACTOR_INSTANCE_RETIRED


# ── duplicate placements: one item id, two live actor rows (H-H8) ────────────
#
# The residual the two write fences left between them, stated in doc 06's
# write-verbs section: the class-key fence guards class-keyed payloads only (an
# instance-keyed write "IS the migration's shape"), and the desk fence counted
# DISTINCT desk ids per persona, so an instance-keyed write claiming an item id
# another live actor already held passed both. Nothing server-side could see it
# — the census joins on ``persona_instance_id`` and never opened
# ``actor.items``, so both holders counted as ``placed`` and the section
# reported ``ok``.
#
# One of those two fences is gone (2026-09-18) and THIS SWEEP IS UNCHANGED BY
# THAT, which is worth stating because the desk-litter census beside it had to
# be deleted on the same day. The difference is what each one asks. This asks
# whether two live actor ROWS claim one item id — a question with no kind in it,
# true of an agent, a desk, or whatever ``ITEM_KINDS`` grows next. The
# desk-litter census asked whether a desk's AGENT HALF was present, and a
# generic desk has none by construction.
#
# It is a READER and was never a fence: a census row moves no write path.

#: Every holder is bound to the SAME live-ish instance — one instance's
#: placement claimed by two live actor rows. A DEFECT: nothing legitimate mints
#: it, and it is the two-fences residual in the shape that actually costs
#: something (the realm-pulled actor file written under a peer's actor key, or a
#: legacy id spelling that canonicalizes onto a key already held).
DUPLICATE_PLACEMENT_SAME_INSTANCE = "same_instance"

#: The holders are different instances. Reported, never a defect: D6 rules that
#: "duplicate desks are fine and only a duplicate on the SAME INSTANCE is not —
#: it's an instantiated system", and item ids are minted persona-scoped
#: (``<persona>_<kind>``), so two instances of one persona each authoring a desk
#: produce exactly this. Calling it a defect would re-key this predicate to the
#: persona, which is the move the ruling forbids.
DUPLICATE_PLACEMENT_CROSS_INSTANCE = "cross_instance"

#: At least one holder is CLASS-KEYED (no instance binding). Reported, never a
#: defect: this is the class→instance re-key migration's own transient —
#: ``scripts/office_actor_rekey_to_instance.py::_apply`` mints the instance-keyed
#: actor with the class-keyed actor's items copied verbatim and only then
#: archives the old key, so both rows briefly claim every id. A census that
#: called it a defect would report the one operator script whose whole job is to
#: move a placement.
DUPLICATE_PLACEMENT_UNBOUND_HOLDER = "unbound_holder"

def _duplicate_placement_reason(bindings: tuple[str, ...]) -> str:
    """Which duplicate this is, from the holders' instance bindings alone.

    ``bindings`` is one entry per HOLDER, ``""`` for a class-keyed actor. Pure,
    total over its input, and — like the desk classifier — the part worth unit
    testing, so it must not be reachable only through a filesystem fixture.

    THE ORDER IS THE DESIGN: the unbound arm is asked first, because a
    class-keyed holder beside an instance-keyed one is also, trivially, a set of
    bindings that is not all-equal, so any other order would file the re-key
    migration's legal transient under ``cross_instance`` and lose the one
    distinction an operator acts on.
    """

    if any(not binding for binding in bindings):
        return DUPLICATE_PLACEMENT_UNBOUND_HOLDER
    if len(set(bindings)) == 1:
        return DUPLICATE_PLACEMENT_SAME_INSTANCE
    return DUPLICATE_PLACEMENT_CROSS_INSTANCE


# ── the census's per-workspace sweeps ────────────────────────────────────────
#
# THREE of them since 2026-09-18: the desk-litter sweep and the agent-item pass
# that fed it left with the desk-litter census (see the note above the orphan
# reasons). The extraction below is unchanged for the three that remain.
#
# Lifted out of :func:`_placement_census_report`, which read the two stores,
# gated them, and then ran several different questions over one workspace loop
# with a pure classifier beside each. The READ and the GATE stay where they are —
# they are the part that has to happen once, in order, for the whole census —
# and what moves is everything after them: each sweep now takes the already-
# gated world and answers with rows, so it can be asked a question directly
# instead of only through two live stores and a doctor section.
#
# They share ONE argument on purpose: ``bindings``, the ``(actor, instance_id)``
# pairs :func:`_census_live_actor_bindings` resolves once per workspace. Every
# sweep needs the actor side of its comparison spelled the way the roster side
# is, and three copies of that resolution is precisely how the two stores came
# to disagree about the same persona.


def _census_live_actor_bindings(scan: Any) -> list[tuple[Any, str]]:
    """The workspace's LIVE actors, each with its canonical instance binding.

    ONE canonical binding per live actor, resolved once here and read by every
    sweep below, so the actor side of every comparison in this workspace is
    spelled the way the roster side is. See :func:`_census_instance_key` for
    what a raw read cost.
    """

    return [
        (actor, _census_instance_key(actor.persona_instance_id, persona_id=actor.persona_id))
        for actor in scan.actors
        if actor.state != "archived"
    ]


def _census_join_workspace(
    workspace_id: str,
    bindings: list[tuple[Any, str]],
    *,
    live_rows: dict[str, Any],
    retired: frozenset[str],
    receipt_for: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """The roster/office join for one workspace: placed, orphans, referenced.

    ``receipt_for`` is a resolver rather than a store, and that is what keeps
    this a function of its arguments: the caller owns the per-census memo, so a
    clean store still reaches zero reads and a test can ask this the retire
    question without a retirement archive on disk. The third element is the set
    of instance ids this workspace REFERENCED, which the caller folds across
    workspaces to decide what is unplaced — returned rather than mutated
    through, because "which rows did this workspace claim" is an answer and not
    a side effect.
    """

    ws_placed: list[dict[str, Any]] = []
    ws_orphans: list[dict[str, Any]] = []
    referenced: set[str] = set()

    for actor, instance_id in bindings:
        if not instance_id:
            # A class-keyed actor answers no roster question: it is keyed on
            # the persona, not on an instance, so it is out of this join by
            # construction rather than by omission.
            continue
        referenced.add(instance_id)
        row = {
            "workspace_id": workspace_id,
            "actor_key": actor.actor_key,
            "persona_id": actor.persona_id,
            "persona_instance_id": instance_id,
        }
        if instance_id in live_rows:
            ws_placed.append(row)
        else:
            # H-H4: WHICH orphan, keyed on the two facts the store holds — a
            # retirement tombstone, and a retire receipt naming this actor key.
            row["reason"] = _orphan_actor_reason(
                actor_key=actor.actor_key,
                instance_id=instance_id,
                retired=retired,
                receipt=receipt_for(instance_id),
            )
            ws_orphans.append(row)
    return ws_placed, ws_orphans, referenced


def _census_duplicate_placements(
    workspace_id: str, bindings: list[tuple[Any, str]]
) -> list[dict[str, Any]]:
    """ITEM ids held by more than one live actor, every holder named (H-H8).

    Over the SAME live actors of the SAME fully-read world. This is the pass
    that opens ``actor.items`` for the JOIN's sake rather than the desk sweep's:
    the join is actor-level, so two live actors holding one item id were both
    counted ``placed`` and the section reported ``ok``.

    Distinct HOLDERS per id, which is the mirror of the write fence's "distinct
    ids per persona": one actor listing an id twice is one holder, because the
    fault named here is two ROWS claiming one placement.
    """

    holders: dict[str, list[dict[str, Any]]] = {}
    for actor, binding in bindings:
        seen_in_actor: set[str] = set()
        for item in actor.items or ():
            item_id = str(getattr(item, "item_id", "") or "").strip()
            if not item_id or item_id in seen_in_actor:
                continue
            seen_in_actor.add(item_id)
            holders.setdefault(item_id, []).append(
                {
                    "actor_key": actor.actor_key,
                    "persona_instance_id": binding or None,
                    "kind": str(getattr(item, "kind", "") or ""),
                }
            )

    ws_duplicates: list[dict[str, Any]] = []
    for item_id, rows in sorted(holders.items()):
        if len(rows) < 2:
            continue
        ws_duplicates.append(
            {
                "workspace_id": workspace_id,
                "item_id": item_id,
                "kinds": sorted({row["kind"] for row in rows if row["kind"]}),
                "holders": rows,
                "reason": _duplicate_placement_reason(
                    tuple(str(row["persona_instance_id"] or "") for row in rows)
                ),
            }
        )
    return ws_duplicates


# ── the census, as phases: read-and-gate once, then questions of the world ────
#
# ``_placement_census_report`` was one 255-line body. Its comment map already
# named the phases — read both stores and gate them, read the retired set once
# with a receipt memo, run the per-workspace sweeps, fold the unplaced rows,
# decide the health — so each is now a function and the verb only sequences
# them. The READ and the GATE still happen once, in order, for the whole census.


@dataclass(frozen=True)
class _CensusWorld:
    """Both stores, read IN FULL and gated — the only thing the sweeps may ask.

    ``receipt_for`` is the per-census retire-receipt memo (H-H4): one read per
    orphaned INSTANCE, never per actor and never on the healthy path, and it
    stays one read across every workspace rather than one per workspace.
    """

    live_rows: dict[str, Any]
    scans: list[tuple[str, Any]]
    retired: frozenset[str]
    receipt_for: Callable[[str], dict[str, Any] | None]


def _census_world() -> _CensusWorld | dict[str, Any]:
    """Read the roster and every workspace's actors; the unknown report on any gap."""

    # ``_normalize_persona_id`` was imported here beside ``OfficeStore`` — the
    # STORE's own spelling of a persona id, borrowed rather than re-derived so
    # the two halves of a persona-level join could not disagree. Its only
    # readers were the desk sweeps (2026-09-18), and the joins that remain are
    # keyed on ``persona_instance_id`` through :func:`_census_instance_key`,
    # which is that same borrow-the-authority rule applied to the other id.
    from ..office_store import OfficeStore
    from ..persona_assignments import PersonaInstanceStore, retired_persona_instance_ids

    unreadable: list[str] = []
    try:
        roster = PersonaInstanceStore().scan_all()
    except Exception as exc:
        return _census_unknown(_error_text(exc))
    if roster.unreadable:
        unreadable.append(f"persona_instances:{roster.unreadable}")
    live_rows = {
        _census_instance_key(row.id, persona_id=row.persona_id): row
        for row in roster.instances
    }
    store = OfficeStore()
    try:
        workspace_ids = list(store.list_workspaces())
    except Exception as exc:
        return _census_unknown(_error_text(exc))
    scans: list[tuple[str, Any]] = []
    for workspace_id in workspace_ids:
        try:
            scan = store.scan_actors(workspace_id)
        except Exception as exc:
            unreadable.append(f"office:{workspace_id} ({_error_text(exc)})")
            continue
        if scan.unreadable:
            unreadable.append(f"office:{workspace_id}:{scan.unreadable}")
        scans.append((workspace_id, scan))
    # EVERY scan first, the partition second, and the gate between them. One
    # unreadable file anywhere in either store is enough to make the JOIN — not
    # merely one row of it — untrustworthy, because the census's two findings
    # are both statements about ABSENCE ("no live actor references this row",
    # "no live row backs this actor") and absence is precisely what a file that
    # would not open is indistinguishable from.
    if unreadable:
        return _census_unknown(
            "unreadable: " + ", ".join(sorted(unreadable)), unreadable=unreadable
        )
    # Read ONCE for the whole census, never per row. The archive is one
    # directory per retire, forever, and ``retired_persona_instance_ids`` says
    # so at its own docstring. It NEVER raises — a listing it could not walk
    # answers the empty set — so it cannot re-open the unreadable gate above.
    # Its remaining reader is the orphan partition (H-H4), which tells an
    # instance this install tombstoned from one it never held.
    retired = retired_persona_instance_ids()
    receipts: dict[str, dict[str, Any] | None] = {}

    def _retire_receipt_for(instance_id: str) -> dict[str, Any] | None:
        if instance_id not in receipts:
            receipts[instance_id] = (
                PersonaInstanceStore().read_retire_receipt(instance_id)
                if instance_id in retired
                else None
            )
        return receipts[instance_id]

    return _CensusWorld(live_rows, scans, retired, _retire_receipt_for)


def _census_sweeps(
    world: _CensusWorld,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
    """``(placed, orphan_actors, duplicate_placements, per_workspace, referenced)``.

    Two sweeps per workspace over ONE resolved binding list. ``referenced`` is
    folded across workspaces, and returned, so the caller decides what is
    unplaced — "which rows did the workspaces claim" is an answer, not a side
    effect.
    """

    placed: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    per_workspace: dict[str, dict[str, Any]] = {}
    referenced: set[str] = set()
    for workspace_id, scan in world.scans:
        bindings = _census_live_actor_bindings(scan)
        ws_placed, ws_orphans, ws_referenced = _census_join_workspace(
            workspace_id,
            bindings,
            live_rows=world.live_rows,
            retired=world.retired,
            receipt_for=world.receipt_for,
        )
        referenced |= ws_referenced
        ws_duplicates = _census_duplicate_placements(workspace_id, bindings)
        placed.extend(ws_placed)
        orphans.extend(ws_orphans)
        duplicates.extend(ws_duplicates)
        per_workspace[workspace_id] = {
            "placed": len(ws_placed),
            "unplaced_rows": [],
            "orphan_actors": ws_orphans,
            "duplicate_placements": ws_duplicates,
            "observed": True,
        }
    return placed, orphans, duplicates, per_workspace, referenced


def _census_unplaced(
    live_rows: dict[str, Any], referenced: set[str], per_workspace: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Live placement-backed rows no live actor references, filed per workspace too."""

    from ..persona_assignments import is_canonical_persona_channel

    unplaced: list[dict[str, Any]] = []
    for key, row in sorted(live_rows.items()):
        if key in referenced:
            continue
        if is_canonical_persona_channel(row):
            # The persona's global operator channel is not a placement and was
            # never meant to hold one. Counting it would report one "unplaced"
            # row per persona on every healthy runtime — a finding the operator
            # can never clear, which is how a census stops being read.
            continue
        entry = {
            "persona_instance_id": key,
            "persona_id": row.persona_id,
            "workspace_id": row.workspace_id,
        }
        unplaced.append(entry)
        bucket = per_workspace.get(row.workspace_id or "")
        if isinstance(bucket, dict) and isinstance(bucket.get("unplaced_rows"), list):
            bucket["unplaced_rows"].append(entry)
    return unplaced


def _census_health(
    orphan_actors: list[dict[str, Any]],
    unplaced_rows: list[dict[str, Any]],
    duplicate_placements: list[dict[str, Any]],
) -> str:
    """The census verdict: an orphan or a ``same_instance`` duplicate is a DEFECT.

    An unplaced row or a non-``same_instance`` duplicate raises the census to
    ``notice`` and NEVER past it: an orphan actor is a defect because it renders
    as an agent nothing can message, while neither of these mis-renders
    anything. Promoting either would turn ``needs_fix`` on for a store with no
    actual fault, and the doctor's whole contract is that its flags mean
    something. A duplicate placement splits on that same line — see
    :func:`_duplicate_placement_reason`. (The ``desk_litter`` term rode the
    notice arm until 2026-09-18 and left with the census that produced it.)
    """

    same_instance_duplicates = [
        row
        for row in duplicate_placements
        if row.get("reason") == DUPLICATE_PLACEMENT_SAME_INSTANCE
    ]
    if orphan_actors or same_instance_duplicates:
        return HEALTH_DEFECT
    if unplaced_rows or duplicate_placements:
        return HEALTH_NOTICE
    return HEALTH_OK


# A4. The orphan half used to read "retiring or re-creating its agent", and for
# the orphan this census reports most often that names the ONE verb that cannot
# work. A realm-pulled placement is born orphaned — office actors sync, persona
# instances are per-install by ruling — so its instance has never existed here,
# and `agent retire` refuses `not_found` terminally. The refusal is correct;
# prescribing it was not. Both repairs are named, keyed on the fact that
# decides between them (does this install hold the instance), never on the id's
# shape.
#
# AX7. The pulled-orphan repair names `--local-only`, and that is not a detail.
# A doctor remediation is DIAGNOSTIC intent: the operator asked what is wrong
# with THIS install's projection, not to delete a placement on every machine in
# the realm. Prescribing the tombstoning form would have this report quietly
# authoring realm-wide deletes on the operator's behalf — the authored form
# stays available, and stays for the moment the operator actually means it.
#
# H-H4 turns the prose split into the rows' own ``reason`` field, so the three
# repairs are keyed on a token a reader can grep rather than on a sentence they
# have to parse — and the sentence now names the tokens instead of
# re-describing the conditions behind them. It names them WITHOUT dropping
# either of the two guarantees A4 and AX7 put in this string: the arms are
# still told apart by a fact rather than a spelling, and the form prescribed for
# the pulled orphan is still the local-only one.
CENSUS_REMEDIATION = (
    "an orphan actor reading retire_incomplete was named by its own "
    "retire's failure list: re-run `agent retire` — retiring or "
    "re-creating its agent still clears it, and the retire's replay "
    "sweeps live placements — or evict the desk from this install with "
    "`harness office actor-remove --workspace <ws> --actor <key> "
    "--local-only`; one reading instance_retired is cleared the same "
    "two ways; one reading instance_unknown — a realm-pulled placement "
    "this install never held, whose instance stayed on the peer — has "
    "nothing to retire and is cleared with actor-remove --local-only "
    "or `runtime.office.remove` alone (drop --local-only only if you "
    "mean to delete the placement realm-wide, which is what the "
    "launcher's own delete does); an unplaced row is either awaiting a "
    "placement or is the roster-only recovery door working as designed; "
    "a duplicate_placements row reading "
    "same_instance is one instance's placement claimed by two live actor "
    "rows — remove or re-place one holder, whose actor_key is named"
)


def _placement_census_report(_context: _DoctorProbeContext | None = None) -> dict[str, Any]:
    """Per-workspace roster/office join: placed, unplaced rows, orphan actors.

    The definitions are the plan's (D1), stated once here because three
    different readings of "placed" is how the two stores drifted in the first
    place:

    * ``placed`` — a LIVE instance-keyed actor whose ``persona_instance_id``
      names a LIVE roster row. Both halves present is the only whole shape.
    * ``unplaced_rows`` — a live placement-backed row (i.e. NOT a canonical
      persona channel, per ``is_canonical_persona_channel``) that no live actor
      references. LEGAL, not a defect: the roster-only door mints exactly this,
      on purpose. Reported as a ``notice`` so an operator can see them without
      the doctor calling a supported gesture broken.
    * ``orphan_actors`` — a live instance-keyed actor whose instance is retired
      or missing. A DEFECT: it renders on the level as an agent nothing can
      message. Each row carries a ``reason`` (H-H4), one of the three
      ``ORPHAN_ACTOR_*`` tokens, because the three have different repairs and
      the remediation string could previously only describe the split in prose.
      ``retire_incomplete`` is the close-the-loop half of the retire's office
      report: a failure the ack named and nothing could see once the ack was
      gone now has a standing detector.
    A fourth finding, ``desk_litter`` (plan DL-H1), lived here until 2026-09-18
    and was REMOVED with the pairing it asked about — schema 10, and the note
    above the orphan reasons has the ruling. Nothing below it is kind-aware:
    every row this section still reports is a claim about an ACTOR or an item
    ID, and a desk answers both exactly as an agent does.

    * ``duplicate_placements`` (H-H8) — an ITEM id held by more than one live
      actor, with every holder named and one of the three
      ``DUPLICATE_PLACEMENT_*`` reasons. A defect only for ``same_instance``;
      the other two are reported at ``notice``, and the reasons are where the
      D6 ruling is spent. The join above could not see any of them: it is
      actor-level, so both holders counted as ``placed`` and the section
      reported ``ok``.

    ``health`` is ``unknown`` — never ``ok`` — when either store could not be
    read in full. That includes a scan that returned rows AND a nonzero
    ``unreadable`` count: a census computed over a short world reports an actor
    as orphaned because its roster row is the file that would not decode, which
    is the exact false finding this doctor's None-not-zero counting rule exists
    to forbid.
    """

    world = _census_world()
    if not isinstance(world, _CensusWorld):
        return world
    placed, orphan_actors, duplicate_placements, per_workspace, referenced = _census_sweeps(world)
    unplaced_rows = _census_unplaced(world.live_rows, referenced, per_workspace)
    return {
        "health": _census_health(orphan_actors, unplaced_rows, duplicate_placements),
        "observed": True,
        "placed": len(placed),
        "placed_actors": placed,
        "unplaced_rows": unplaced_rows,
        "orphan_actors": orphan_actors,
        "duplicate_placements": duplicate_placements,
        "workspaces": per_workspace,
        "remediation": CENSUS_REMEDIATION,
    }
