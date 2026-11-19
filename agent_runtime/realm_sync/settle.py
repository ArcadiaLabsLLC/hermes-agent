"""Taking the team's copy settles every baseline it touched: one rule, beside the drift walk.

RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE (review w1118a.40 D11). An operation that only adopts
the team's copy — a pull applier, a take-remote resolve, a revert — must leave nothing to publish. The drift
walk (:mod:`.drift`) is the one definition of "unpublished": per family a hash and a scope. So every adopt
records, for each key it adopted, the hash the walk computes for the body AS WRITTEN, and drops a baseline
entry whose owner left the walk's scope. Four cases had each written their baseline their own way and three
disagreed with the walk: the remote hash for a body written differently (the surface's tombstone union), no
entry at all (take-remote before cae912bae4), and an entry outside the walk's scope (a drawing whose desk left).

The arms, one per family that needs one:

* office actor — :func:`settle_office_actor` (the take-remote resolve; cae912bae4's per-desk settle, moved here);
* office surface — :func:`settle_office_surface` (the pull's surface arm);
* flow graph — :func:`settle_flow_graph_scope` (the pull, take-remote and revert: the walk's scope);
* persona instance — none here: the walk reads the pull's dropped-steering ledger
  (``persona_instance_sync.pull.body_as_pulled``, 308a54da63), and the revert takes the realm's hash
  (``realm_revert_writes.instance_baseline_after_revert``).

Rejected (D11): a fifth per-case patch, the walk skipping benign cases (a second owner of what the team has),
and subtracting the tombstone union inside the walk (two hash definitions).
"""

from __future__ import annotations

from collections.abc import Iterable

from .. import office_models
from ..models import OfficeActor, OfficeSurface

__layer__ = "stores"

__all__ = [
    "settle_flow_graph_scope",
    "settle_flow_graph_scope_for_realm",
    "settle_flow_graph_scope_for_workspace",
    "settle_office_actor",
    "settle_office_surface",
]


def settle_office_actor(workspace_id: str, actor_key: str, actor: OfficeActor | None) -> str | None:
    """ONE desk's entry after the member took the team's copy of it: the adopted desk's hash as the walk computes
    it, or no entry for a desk the team removed (the pull's archive arm pops it with the row). That key only —
    re-baselining the workspace would bless the member's other unpublished office edits. A workspace with no
    realm has no baseline. Returns the realm settled, or ``None``."""

    from ..errors import NotFound
    from ..office_sync import _actor_key, read_office_baseline, write_office_baseline
    from ..store import WorkspaceStore

    try:
        realm_id = WorkspaceStore().get(workspace_id).realm_id
    except NotFound:
        return None
    if not realm_id:
        return None
    baseline = read_office_baseline(realm_id)
    key = _actor_key(workspace_id, actor_key)
    settled = dict(baseline)
    if actor is None:
        settled.pop(key, None)
    else:
        settled[key] = office_models.office_content_hash(actor)
    if settled != baseline:
        write_office_baseline(realm_id, settled)
    return realm_id


def settle_office_surface(baseline: dict[str, str], written: OfficeSurface) -> None:
    """The pull's surface arm: the hash of the surface AS WRITTEN. ``adopt_remote_surface`` unions this
    machine's own tombstones into the team's ledger; stamping the REMOTE hash left that union reading as an
    "office layout changed" nobody made (RT-REALM-PULL-OF-A-NET-ZERO-DESK-DELETE-LEAVES-OFFICE-LAYOUT-CHANGED,
    folded into D11)."""

    from ..office_sync import _surface_key

    baseline[_surface_key(written.workspace_id)] = office_models.office_content_hash(written)


def settle_flow_graph_scope(realm_id: str, owner_ids: Iterable[str]) -> list[str]:
    """Drop every drawing baseline entry whose owner desk is outside the walk's scope (``owner_ids``: the desks
    this realm ships, :func:`.drift.flow_graph_walk_scope`). The walk reads such an entry as "drawing no longer
    published" whether or not the realm still carries the drawing — a teammate's desk removal, taken by a pull
    or a take-theirs, left exactly that (RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-DESK-REMOVED-BY-HAND-OFFERS-ITS-
    DRAWING, folded into D11). The drawing file is never touched. Returns the released graph ids."""

    from ..flow_graph import owner_instance_id_of
    from ..flow_graph_sync import flow_graph_baseline_key, read_flow_graph_baseline, write_flow_graph_baseline

    scope = set(owner_ids)
    baseline = read_flow_graph_baseline(realm_id)
    prefix = flow_graph_baseline_key("")
    released = sorted(
        key[len(prefix):]
        for key in baseline
        if key.startswith(prefix) and owner_instance_id_of(key[len(prefix):]) not in scope
    )
    if released:
        for graph_id in released:
            del baseline[flow_graph_baseline_key(graph_id)]
        write_flow_graph_baseline(realm_id, baseline)
    return released


def settle_flow_graph_scope_for_workspace(workspace_id: str) -> list[str]:
    """:func:`settle_flow_graph_scope` for the realm a workspace is published into (the take-remote resolve
    holds only a workspace). No realm, nothing to settle."""

    from ..errors import NotFound
    from ..store import RealmStore, WorkspaceStore

    try:
        realm_id = WorkspaceStore().get(workspace_id).realm_id
        realm = RealmStore().get(realm_id) if realm_id else None
    except NotFound:
        return []
    if realm is None:
        return []
    return settle_flow_graph_scope_for_realm(realm)


def settle_flow_graph_scope_for_realm(realm) -> list[str]:
    """:func:`settle_flow_graph_scope` over the walk's own scope for this realm."""

    from .artifacts import _workspaces_for_realm
    from .drift import flow_graph_walk_scope

    return settle_flow_graph_scope(realm.id, flow_graph_walk_scope(_workspaces_for_realm(realm)))
