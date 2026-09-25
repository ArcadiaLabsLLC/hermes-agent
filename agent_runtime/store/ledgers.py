"""The realm ledger rules: skill tombstones, workspace lifts, the settled-first
bound (``prune_settled_ledger``), the ONE ledger-stamp reader (``ledger_time``),
the two caps and the two selection normalizers. Pure over ``models``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from hermes_time import now

from ..models import Realm, SkillTombstone, WorkspaceLift
from ..serde import safe_id

__layer__ = "policy"

T = TypeVar("T")


# Bound on Realm.deleted_workspace_ids — the workspace-delete resurrection
# guard. Oldest entries fall off first; by then every member has long since
# pulled the tombstone (the bounded-ledger idiom shared with the board/office
# archived ledgers).
DELETED_WORKSPACE_LEDGER_CAP = 500
# Bound on Realm.skill_tombstones — the same guard for shared skills. Smaller
# than the workspace cap because the shared catalog is small; the eviction
# argument is identical (by the time an entry falls off, every member has long
# since pulled it).
SKILL_TOMBSTONE_LEDGER_CAP = 200


def _normalize_skill_selection(selection: list[str] | None) -> list[str]:
    """Validate (shape only), dedupe, and sort skill selection slugs.

    Shape rules (per REALM_SKILL_SELECTION_DESIGN §2): non-empty, no leading
    dot, no path separator, and identical to their ``safe_path_token`` form — the
    same tokenizer the realm publisher uses for skill directory names, so a
    valid slug round-trips to its published path. Every malformed slug is
    collected and reported in ONE ``ValueError`` (mapped to a typed
    ``invalid_request`` at the CLI seam) so a batch save names all offenders
    instead of failing on the first. Slugs unknown to the local catalog are
    NOT filtered here — that is realm truth another member may own.
    """
    from agent_runtime.paths import safe_path_token

    cleaned: set[str] = set()
    rejected: list[str] = []
    for raw in selection or []:
        slug = str(raw).strip()
        if (
            not slug
            or slug.startswith(".")
            or "/" in slug
            or "\\" in slug
            or slug != safe_path_token(slug)
        ):
            rejected.append(slug or repr(raw))
            continue
        cleaned.add(slug)
    if rejected:
        raise ValueError(
            "malformed skill selection slug(s): " + ", ".join(repr(slug) for slug in sorted(set(rejected)))
        )
    return sorted(cleaned)


def skill_tombstone_matches(entry_slug: str, slug: str) -> bool:
    """Does ledger entry ``entry_slug`` block the package published as ``slug``?

    Mirrors ``realm_sync._skill_slug_selected`` exactly: the slug itself, or —
    for a categorized ``<cat>/<child>`` slug — its bare child name. The
    selection and the tombstone MUST agree about what a name means, or a slug
    could be simultaneously "selected" and "not the thing that was deleted".

    Public because the operator delete verb (``hermes harness skills delete``)
    asks the rule while holding a CANDIDATE entry slug and no realm yet — "which
    canonical packages would a tombstone on this name cover, and which realms
    currently publish one of them" — a question :func:`skill_tombstoned` cannot
    be asked, since there is no ledger to read. Two entry points, ONE rule; a
    second spelling in the CLI is precisely what §2.3 forbids.

    Because the rule is deliberately identical to the SELECTION rule, the same
    function answers "is this package selected" as
    ``any(skill_tombstone_matches(entry, slug) for entry in selection)``.
    """

    if entry_slug == slug:
        return True
    if "/" in slug:
        return entry_slug == slug.split("/", 1)[1]
    return False


#: Historical private name, kept for this module's own call sites (the
#: ``validate_skill_slug`` / ``_validate_slug`` idiom in ``skill_promotion``).
_tombstone_blocks = skill_tombstone_matches


def active_skill_tombstones(realm: Realm) -> list[SkillTombstone]:
    """The ledger entries that currently BLOCK — the ONE spelling of "active".

    Since RD-11 the ledger is a per-slug state register: a restored entry stays
    on it (carrying ``restored_at``) so the union merge can see the restore, but
    it blocks nothing. Every reader that used to mean "is there an entry for
    this slug" — the match rule below, the receipt rows, the two CLI verbs'
    before-the-write questions — asks through here instead, so "active" cannot
    acquire a second, drifting definition the way an open-coded
    ``entry.slug == slug`` scan would.
    """

    return [
        entry
        for entry in (getattr(realm, "skill_tombstones", None) or [])
        if getattr(entry, "restored_at", None) is None
    ]


def prune_settled_ledger(items: list[T], *, cap: int, settled: Callable[[Any], bool]) -> list[T]:
    """Bound a per-key state register, dropping SETTLED history first.

    ``items`` is oldest-first (the append order every ledger chokepoint keeps).
    A plain ``items[-cap:]`` would let restored — i.e. inert — entries push
    LIVE blocks off the front, which is the one eviction this ledger must never
    make: an evicted block is a resurrected skill. So settled entries are
    dropped oldest-first until the list fits, and only then does the ordinary
    oldest-first bound apply.

    Shape-agnostic (``settled`` is supplied by the caller) because the same rule
    runs twice: over :class:`SkillTombstone` records at the store chokepoints,
    and over raw JSON rows in ``realm_sync``'s pull-time union merge, which must
    stay tolerant of a peer's unparseable stamps. One rule, two shapes.
    """

    if cap <= 0 or len(items) <= cap:
        return list(items)
    over = len(items) - cap
    dropped: set[int] = set()
    for index, item in enumerate(items):
        if len(dropped) >= over:
            break
        if settled(item):
            dropped.add(index)
    kept = [item for index, item in enumerate(items) if index not in dropped]
    return kept[-cap:]


def _prune_skill_tombstones(entries: list[SkillTombstone]) -> list[SkillTombstone]:
    """The record-shaped half of :func:`prune_settled_ledger`."""

    return prune_settled_ledger(
        entries,
        cap=SKILL_TOMBSTONE_LEDGER_CAP,
        settled=lambda entry: getattr(entry, "restored_at", None) is not None,
    )


def workspace_lift_is_active(lift: Any) -> bool:
    """Is this lift marker the LATEST word about its workspace id?

    Shape-tolerant on purpose (record here, raw JSON row in the pull-time merge
    over a peer's bytes — the same "one rule, two shapes" split
    :func:`prune_settled_ledger` carries). A marker whose ``deleted_at`` is at
    least as new as its ``restored_at`` has been superseded by a re-delete; the
    tie resolves to the DELETE, matching the skill ledger's rule.
    """

    restored_at = lift.get("restored_at") if isinstance(lift, dict) else getattr(lift, "restored_at", None)
    deleted_at = lift.get("deleted_at") if isinstance(lift, dict) else getattr(lift, "deleted_at", None)
    restored_at = ledger_time(restored_at)
    if restored_at is None:
        return False
    deleted_at = ledger_time(deleted_at)
    return deleted_at is None or restored_at > deleted_at


def ledger_time(value: Any) -> "datetime | None":
    """A ledger stamp as an aware datetime, or ``None`` when it will not parse.

    The ONE authority for reading a ledger stamp. ``realm_sync`` carried a
    byte-identical copy of this body under the name ``_ledger_time`` until
    2026-09-06, when ``test_duplicate_helper_bodies`` finally ran on CI and
    named the pair; ``realm_sync`` already imports from this module, so the
    lower layer is where the body belongs and the name went public with it.

    Deliberately tolerant, and deliberately NOT ``serde.from_jsonable``: at pull
    time this runs over a PEER's bytes, where an unparseable stamp must cost
    that one entry its rank in the merge and nothing more. A naive stamp is read
    as UTC — that is the only timezone any writer in this lane mints.
    """

    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _prune_workspace_lifts(entries: list[WorkspaceLift]) -> list[WorkspaceLift]:
    """The record-shaped bound. SUPERSEDED markers are the settled history here:
    a re-deleted id is back on ``deleted_workspace_ids``, so dropping its marker
    loses nothing, while dropping a LIVE lift would re-delete a live workspace."""

    return prune_settled_ledger(
        entries,
        cap=DELETED_WORKSPACE_LEDGER_CAP,
        settled=lambda entry: not workspace_lift_is_active(entry),
    )


def lift_deleted_workspace(realm: Realm, workspace_id: str) -> bool:
    """Take ``workspace_id`` off the delete ledger AND say so to the peers.

    The single write chokepoint for a lift, and it exists because the local half
    alone is not a restore: removing the id is an absence, and RD-11's set-union
    merge reads an absence as "that member never heard about the delete", so the
    next pull from any peer still carrying the id undid the lift. The marker is
    the propagating half — a positive fact with a clock that can win the merge.

    Mutates ``realm`` IN MEMORY and reports whether anything changed, because
    both call sites (``default_scope``) batch several realm edits behind one
    ``realm_changed`` flag and a single save. Idempotent: an id that is neither
    on the ledger nor already lifted writes nothing.
    """

    clean = str(workspace_id or "").strip()
    if not clean:
        return False
    ledger = list(realm.deleted_workspace_ids or [])
    lifts = list(getattr(realm, "workspace_lifts", None) or [])
    already = any(lift.workspace_id == clean and workspace_lift_is_active(lift) for lift in lifts)
    if clean not in ledger and already:
        return False
    realm.deleted_workspace_ids = [item for item in ledger if item != clean]
    # One marker per id: a re-lift RE-STAMPS rather than appending, so the
    # register cannot hold two contradictory rows for one workspace.
    lifts = [lift for lift in lifts if lift.workspace_id != clean]
    lifts.append(WorkspaceLift(workspace_id=clean, restored_at=now()))
    realm.workspace_lifts = _prune_workspace_lifts(lifts)
    return True


def skill_tombstoned(realm: Realm, slug: str) -> SkillTombstone | None:
    """The ONE spelling of "is this skill deleted in this realm".

    Every enforcement point (the pull's inbox mirror and canonical archive, the
    publish artifact filter, the operator surfaces) asks through here, so a
    second, drifting copy of the match rule cannot exist. Returns the blocking
    entry (evidence for the refusal message) or ``None`` — a RESTORED entry is
    not a blocking one, so the scan runs over the active ledger.
    """

    clean = str(slug or "").strip()
    if not clean:
        return None
    for entry in active_skill_tombstones(realm):
        if _tombstone_blocks(entry.slug, clean):
            return entry
    return None


def _normalize_agent_selection(selection: list[str] | None) -> list[str]:
    """Validate, dedupe, and sort Realm persona-definition ids.

    Persona ids use the store's canonical model-id grammar (including ``:``
    for profile-backed personas). Unknown ids are deliberately preserved: a
    different Realm member may own the definition locally, so filtering an
    unrelated save through this machine's catalog would corrupt Realm truth.
    Every malformed id is reported together and no partial write occurs.
    """
    cleaned: set[str] = set()
    rejected: list[str] = []
    for raw in selection or []:
        value = str(raw).strip()
        normalized = safe_id(value)
        if not value or normalized is None or value != normalized:
            rejected.append(value or repr(raw))
            continue
        cleaned.add(value)
    if rejected:
        raise ValueError(
            "malformed agent selection id(s): "
            + ", ".join(repr(value) for value in sorted(set(rejected)))
        )
    return sorted(cleaned)
