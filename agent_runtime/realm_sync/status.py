"""``realm_sync_status``: the diagnostic read — remote freshness when allowed, local facts always."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

from .. import paths
from ..models import Workspace
from ..store import RealmStore
from .models import RealmMembershipProvider, RealmSyncError, _safe_display_path
from .ledgers import _skill_tombstone_rows
from .git import (
    _authorize,
    _ensure_repo_gitattributes,
    _ensure_sync_repo,
    _git_state,
    _refresh_remote_tracking,
    _sync_repo_path,
    _sync_state,
)
from .publish_scans import _level_publish_scan, _map_publish_scan, _office_publish_scan
from .artifacts import (
    _distinct_skill_package_count,
    _flow_graph_projection,
    _workspaces_for_realm,
    realm_agent_selection_state,
    resolve_realm_sync_artifacts,
)
from .drift import (
    _BOARD_DRIFT_COUNTS,
    _FLOW_GRAPH_DRIFT_COUNTS,
    _OFFICE_DRIFT_COUNTS,
    _PERSONA_INSTANCE_DRIFT_COUNTS,
    _SKILL_DRIFT_COUNTS,
    _any_store_drift,
    _drift_counts,
    store_drift_items,
)
from .sidecar import (
    _held_profile_artifacts,
    _timestamp_file,
    _workspace_sync_statuses,
    _write_sync_sidecar,
)
from .skill_inbox import _held_skill_packages_for_realm

__layer__ = "lanes"
__all__ = [
    "_flow_graph_status_row",
    "_level_status_row",
    "_map_status_row",
    "realm_sync_status",
]


def realm_sync_status(
    realm_id: str,
    *,
    membership: RealmMembershipProvider | None = None,
    credential: "RealmSyncCredential | None" = None,
) -> dict[str, Any]:
    realm = RealmStore().get(realm_id)
    # The authorization gates the REMOTE half of this verb — the fetch, the
    # clone, and therefore the freshness of ahead/behind — and nothing else.
    # Everything below it (store drift, held skill packages, held profile
    # artifacts, workspace publication statuses, the git state already on this
    # disk) is a LOCAL read that needs no credential, and refusing the whole
    # verb over the remote half deleted the diagnostic exactly when it was most
    # wanted: a member whose credential expired got no drift, no held-artifact
    # list and no workspace rows, only ``sync_auth_failed``. A diagnostic read
    # DEGRADES; it does not vanish.
    #
    # The degrade rides the SAME honesty pair an unreachable remote already
    # rides (``remote_checked`` / ``remote_check_error``) rather than a new key:
    # from the launcher's side "hermes could not reach the realm remote" and
    # "hermes was not allowed to" are the same fact — the state below is the
    # last known local picture — and it already has a renderer for it
    # (``_RemoteUncheckedNote``).
    auth_error: RealmSyncError | None = None
    try:
        _authorize(realm, "status", membership, credential)
    except RealmSyncError as exc:
        auth_error = exc
    if auth_error is None:
        repo = _ensure_sync_repo(realm, credential=credential)
        # Refresh the remote-tracking ref FIRST: ahead/behind below are computed
        # against ``@{u}``, and without a fetch that ref is whatever the last
        # pull/publish left behind — a member editing (or deleting) files upstream
        # stayed invisible to "Check now" forever, so the update-policy banner
        # never fired. Best-effort: an offline check still answers from the local
        # state, and says so via ``remote_checked``.
        remote_check = _refresh_remote_tracking(repo, credential=credential)
    else:
        # THE FLOOR of the degrade, and it is deliberate: a degraded read
        # answers from local facts, so where there are none it still refuses
        # with the code it refused with before. ``_ensure_sync_repo`` is not
        # called at all here — its remote branch CLONES, which is the very
        # operation just denied, and an ``init`` in its place would leave an
        # empty repo that the next ``_ensure_sync_repo`` mistakes for a
        # completed clone and never re-clones.
        repo = _sync_repo_path(realm)
        if not (repo / ".git").exists():
            raise auth_error
        _ensure_repo_gitattributes(repo)
        remote_check = {"checked": False, "error": auth_error.code}
    git = _git_state(repo)
    artifacts = resolve_realm_sync_artifacts(realm_id)
    agent_state = realm_agent_selection_state(realm_id)
    workspaces = _workspaces_for_realm(realm)
    workspace_statuses = _workspace_sync_statuses(realm, repo)
    # Installs that predate the skill baseline sidecar (2026-09-12): record the
    # agreement between canonical and inbox as the baseline BEFORE the held read
    # and the drift walk below decide against it, so the operator's first local
    # edit after the lane landed reads ``changed`` rather than ``held``.
    from ..skill_promotion import realm_inbox_dir as _realm_inbox_dir
    from ..skill_sync import record_converged_skill_baselines

    record_converged_skill_baselines(realm.id, _realm_inbox_dir(realm.id))
    skills_drift = _held_skill_packages_for_realm(realm)
    state = _sync_state(git)
    # Local store drift vs the never-synced baseline sidecar: the git state above
    # only knows the checked-out realm repo, so a local board card add or an
    # archived office actor — neither of which touches the repo until publish —
    # leaves git ``in_sync`` while real unpublished changes sit in the store.
    # This surfaces that honestly (pure hash/baseline compare — no extra
    # git/network on the status path).
    # ONE walk per family, and the counts derived from its rows. ``items`` is
    # ADDITIVE (absent-tolerant on the launcher side): the counts keep their
    # exact shape, and the rows are what makes a per-item revert addressable at
    # all — a count nothing can name is a change with no exit but Publish.
    drift_items = store_drift_items(realm.id, workspaces)
    store_drift = {
        "boards": _drift_counts(drift_items, _BOARD_DRIFT_COUNTS),
        "office": _drift_counts(drift_items, _OFFICE_DRIFT_COUNTS),
        # Additive third family (instance-replication H4). ``_any_store_drift``
        # sums every family it finds, so a locally-authored agent nobody has
        # published now lights "unpublished changes" — which is the honest
        # answer, and exactly the reason the office family was added on 2026-08-29
        # ("the sheet kept saying In sync while the local store had drifted").
        "persona_instances": _drift_counts(drift_items, _PERSONA_INSTANCE_DRIFT_COUNTS),
        # Additive fourth family (canvas-replication w13/h2, revert arm w17/hb).
        # It arrives WITH its revert arm, which is why it was not here before:
        # a drift row the revert lane cannot address is an exit that does not
        # exist. ``_any_store_drift`` sums it like the rest, so an unpublished
        # drawing now lights "unpublished changes" instead of being visible only
        # as a count on the ``flow_graphs`` row below.
        "flow_graphs": _drift_counts(drift_items, _FLOW_GRAPH_DRIFT_COUNTS),
        # Additive fifth family (held-skill-publish-direction §4.5). It arrives
        # WITH its revert arm and its resolve verb, for the canvas family's
        # reason: a drift row the operator cannot address is an exit that does
        # not exist.
        "skills": _drift_counts(drift_items, _SKILL_DRIFT_COUNTS),
        "items": [item.as_dict() for item in drift_items],
    }
    profile_artifacts_held = _held_profile_artifacts(realm, repo)
    _write_sync_sidecar(
        realm,
        repo=repo,
        git=git,
        skills_drift=skills_drift,
        artifacts=artifacts,
        profile_artifacts_held=profile_artifacts_held,
    )
    return {
        "schema_version": 1,
        "id": realm.id,
        "kind": "realm_sync",
        "state": state,
        "ahead": git["ahead"],
        "behind": git["behind"],
        # Additive honesty pair for the fetch above (absent-tolerant consumers):
        # ``remote_checked`` is True only when a remote exists AND the fetch
        # succeeded — i.e. ahead/behind reflect the real upstream right now.
        # When False, ``remote_check_error`` carries the typed code (or None for
        # a repo with no remote at all). It also carries the AUTHORIZATION code
        # (``sync_auth_failed`` / ``role_insufficient`` / …) when the remote half
        # was denied and this verb degraded to local facts — see the top of this
        # function for why a denial answers here rather than raising.
        "remote_checked": remote_check["checked"],
        "remote_check_error": remote_check["error"],
        "skills_drift": skills_drift,
        "skill_publish_mode": realm.skill_publish_mode,
        "skill_selection": sorted(realm.skill_selection or []),
        # Additive: the realm's skill-delete ledger as receipt rows. The
        # launcher's realm-sync sheet reads this envelope absent-tolerantly, so
        # a "deleted from realm" row with a restore affordance needs nothing
        # else from the backend.
        "skill_tombstones": _skill_tombstone_rows(realm),
        "skills_published": _distinct_skill_package_count(artifacts),
        "agent_publish_mode": agent_state["mode"],
        "agent_selection": agent_state["selection"],
        "agents_published": len(agent_state["published"]),
        "conflicts": git["conflicts"],
        "last_pull": _timestamp_file(repo, "last_pull.txt"),
        "last_publish": _timestamp_file(repo, "last_publish.txt"),
        "artifacts": len(artifacts),
        "sync_repo": _safe_display_path(repo),
        "workspace_statuses": workspace_statuses,
        # Additive honesty fields (launcher consumes these; absent-tolerant).
        # ``state``/``ahead``/``behind`` are UNCHANGED — other consumers key off
        # them — this only ADDS store-vs-baseline drift accounting on top.
        "store_drift": store_drift,
        "unpublished_changes": _any_store_drift(store_drift),
        # Held profile FILES (MEMORY.md / core context / persona prompts whose
        # member copy diverged from the realm's). A hold the operator cannot see
        # is the same as a loss, so it is surfaced here and resolvable with
        # ``hermes harness realm sync resolve <realm> --key <k> --take …``.
        "profile_artifacts_held": profile_artifacts_held,
        # The canvas family's accounting, so "this chart is empty because the
        # drawing did not travel / is held / would not read" is answerable from
        # the envelope rather than from a store walk. Additive and
        # absent-tolerant, like every honesty field above it.
        "flow_graphs": _flow_graph_status_row(realm.id, workspaces),
        # The workspace LEVEL family's accounting, same shape and same
        # absent-tolerant contract as the row above it.
        "levels": _level_status_row(realm.id, workspaces),
        # The MAP CATALOGUE family's accounting. Same shape and same
        # absent-tolerant contract as the row above it, minus the workspace
        # argument: a map id is not addressed by a workspace, so the scan has no
        # realm filter to take.
        "maps": _map_status_row(realm.id),
    }


def _map_status_row(realm_id: str) -> dict[str, Any]:
    """``{publishable, unpublished, held, refused}`` for the map catalogue.

    A top-level key and NOT a ``store_drift`` family, for the reason
    :func:`_level_status_row` spells out one function down: ``realm_revert``
    subscripts ``_PROCESS_ORDER[row.family]`` directly and dispatches on family
    for the upstream lookup, the baseline and the store door, so a family added
    there without a revert arm hands ``revert --all`` a ``KeyError`` and offers
    the operator an exit that does not exist. The map family's revert arm is a
    follow-up with its own row, exactly as the level family's is.
    """

    from ..map_sync import map_baseline_key, read_map_baseline

    scan = _map_publish_scan()
    baseline = read_map_baseline(realm_id)
    unpublished = sum(
        1
        for token, body_hash in scan.hashes.items()
        if baseline.get(map_baseline_key(token)) != body_hash
    )
    conflicts = paths.realm_sync_root() / paths.safe_path_token(realm_id) / "map_conflicts"
    held = sorted(path.stem for path in conflicts.glob("*.json")) if conflicts.is_dir() else []
    return {
        "publishable": len(scan.artifacts),
        "unpublished": unpublished,
        "held": held,
        "refused": list(scan.refused),
    }


def _level_status_row(realm_id: str, workspaces: list[Workspace]) -> dict[str, Any]:
    """``{publishable, unpublished, held, refused}`` for the workspace LEVEL family.

    **A top-level key and DELIBERATELY NOT a ``store_drift`` family**, and the
    reason is the one :func:`_flow_graph_status_row` records for why the canvas
    was not one either until its revert arm landed: ``store_drift`` rows are
    exactly the set the REVERT lane addresses. ``realm_revert`` sorts them
    through ``_PROCESS_ORDER[row.family]`` — a direct subscript — and dispatches
    on family for the upstream lookup, the baseline and the store door. A family
    added there without a revert arm hands ``revert --all`` a ``KeyError`` and
    offers the operator an exit that does not exist, so the level family's revert
    arm is a follow-up with its own row, and until it lands this key carries the
    same arithmetic in the shape that has no such promise attached.

    ``unpublished`` is the identical hash-vs-baseline compare the publish scan
    makes, spent here as a count — one walk's arithmetic in two shapes, never
    two walks.
    """

    from ..level_sync import level_baseline_key, read_level_baseline

    scan = _level_publish_scan(workspaces)
    baseline = read_level_baseline(realm_id)
    unpublished = sum(
        1
        for token, body_hash in scan.hashes.items()
        if baseline.get(level_baseline_key(token)) != body_hash
    )
    conflicts = paths.realm_sync_root() / paths.safe_path_token(realm_id) / "level_conflicts"
    held = sorted(path.stem for path in conflicts.glob("*.json")) if conflicts.is_dir() else []
    return {
        "publishable": len(scan.artifacts),
        "unpublished": unpublished,
        "held": held,
        "refused": list(scan.refused),
    }


def _flow_graph_status_row(realm_id: str, workspaces: list[Workspace]) -> dict[str, Any]:
    """``{publishable, unpublished, held, unreadable}`` for the canvas family.

    **Why this is a top-level key AS WELL AS a ``store_drift`` family.** It was
    only this one until 2026-09-05: ``store_drift`` rows are exactly the set the
    REVERT lane addresses, ``realm_revert`` sorts them through
    ``_PROCESS_ORDER[row.family]`` — a direct subscript — and dispatches on
    family for the upstream lookup, the baseline and the store door, so a family
    added there without a revert arm would have handed ``revert --all`` a
    ``KeyError`` and offered the operator an exit that does not exist. The
    canvas revert arm landed (w17/hb) and the rows landed with it.

    What stays here is what a drift row cannot say: ``publishable`` (how many
    drawings this realm ships at all), ``held`` (conflict sidecars — a hold is
    not drift, and reverting one would discard the parked remote), and
    ``unreadable`` (a canvas the projection refuses, which has no revertable
    row by construction). ``unpublished`` is the same hash-vs-baseline compare
    ``_flow_graph_store_drift_items`` makes, spent here as a count — one walk's
    arithmetic in two shapes, never two walks.
    """

    from ..flow_graph_sync import flow_graph_baseline_key, read_flow_graph_baseline

    scan = _office_publish_scan(workspaces)
    projection = _flow_graph_projection(scan.instance_ids)
    baseline = read_flow_graph_baseline(realm_id)
    unpublished = sum(
        1
        for graph_id, body_hash in projection.hashes().items()
        if baseline.get(flow_graph_baseline_key(graph_id)) != body_hash
    )
    conflicts = paths.realm_sync_root() / paths.safe_path_token(realm_id) / "flow_graph_conflicts"
    held = sorted(path.stem for path in conflicts.glob("*.json")) if conflicts.is_dir() else []
    return {
        "publishable": len(projection.graphs),
        "unpublished": unpublished,
        "held": held,
        "unreadable": list(projection.unreadable),
    }
