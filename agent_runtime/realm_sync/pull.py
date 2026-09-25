"""``pull_realm_sync``: overwrite the generic families, then run every applier in order.

Also the secret scan both verbs run and the realm-JSON ledger reconciliation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from agent_runtime.profile_home import get_shared_skills_dir

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

from .. import paths
from ..config import ensure_persisted_personas, load_agent_runtime_config
from ..models import Realm
from ..redaction import SECRET_ASSIGNMENT_RE
from ..skill_install import HARNESS_SKILLS, install_harness_skills, install_harness_skills_for_personas
from ..store import RealmStore, skill_tombstoned
from .models import (
    RealmMembershipProvider,
    RealmSyncArtifact,
    RealmSyncError,
    _canonicalize_text_bytes,
)
from .families import SyncFamily, _is_hard_excluded_path, _is_secretish_path
from .ledgers import (
    _REALM_AUTHORITY_FIELDS,
    _UNIONED_REALM_LEDGERS,
    merge_deleted_workspace_ledgers,
    merge_skill_tombstone_ledgers,
    merge_workspace_lift_ledgers,
)
from .git import (
    _authorize,
    _credential_git_config,
    _ensure_sync_repo,
    _git,
    _git_state,
    _has_remote,
    _realm_subtree,
)
from .persona_artifacts import _artifacts_from_subtree
from .artifacts import _iter_publishable_skill_packages
from .sidecar import _append_realm_sync_event, _sync_result, _write_sync_sidecar, _write_timestamp
from .skill_inbox import apply_skill_inbox_pull

__layer__ = "lanes"
__all__ = [
    "PULL_APPLIERS",
    "PullApplier",
    "_PullRun",
    "_apply_skill_tombstones",
    "_apply_workspace_tombstones",
    "_artifact_contains_secret_assignment",
    "_assert_no_secret_artifacts",
    "_file_contains_secret_assignment",
    "_overwrite_generic_families",
    "_pull_accounting",
    "_pull_boards",
    "_pull_flow_graphs",
    "_pull_level",
    "_pull_map",
    "_pull_office",
    "_pull_persona_config",
    "_pull_persona_instances",
    "_pull_profile_files",
    "_pull_skill_inbox",
    "_pull_skill_tombstones",
    "_pull_workspace_tombstones",
    "_pulled_artifact_bytes",
    "pull_realm_sync",
]


def pull_realm_sync(
    realm_id: str,
    *,
    dry_run: bool = False,
    membership: RealmMembershipProvider | None = None,
    credential: "RealmSyncCredential | None" = None,
) -> dict[str, Any]:
    """Pull this realm: the generic overwrite loop, then every applier in
    ``PULL_APPLIERS`` order, then the skill reconcile and the report."""

    realm = RealmStore().get(realm_id)
    _authorize(realm, "pull", membership, credential)
    repo = _ensure_sync_repo(realm, credential=credential)
    git = _git_state(repo)
    if git["conflicts"]:
        raise RealmSyncError("sync_conflict", "Realm sync repo has unresolved git conflicts.", safe_details={"conflicts": git["conflicts"]})
    if _has_remote(repo):
        _git(repo, "pull", "--ff-only", extra_config=_credential_git_config(credential))
    subtree = _realm_subtree(repo, realm.id)
    artifacts = _artifacts_from_subtree(subtree)
    _assert_no_secret_artifacts(artifacts)
    if dry_run:
        return _sync_result(realm, "pull", "dry_run", artifacts, repo=repo, git=_git_state(repo), changed=False)
    run = _PullRun(realm=realm, subtree=subtree, changed=_overwrite_generic_families(artifacts, realm=realm))
    for applier in PULL_APPLIERS:
        if applier.apply(run):
            run.changed = True
    install_results = [
        *install_harness_skills(skills=sorted(HARNESS_SKILLS)),
        *install_harness_skills_for_personas(ensure_persisted_personas(load_agent_runtime_config())),
    ]
    _write_timestamp(repo, "last_pull.txt")
    git_after = _git_state(repo)
    result = _sync_result(run.realm, "pull", "pulled", artifacts, repo=repo, git=git_after, changed=run.changed)
    result.update(_pull_accounting(run, install_results))
    _write_sync_sidecar(
        run.realm,
        repo=repo,
        git=git_after,
        skills_drift=run.skill.held,
        artifacts=artifacts,
        profile_artifacts_held=sorted(set(run.profile_files.held)),
    )
    _append_realm_sync_event(
        "realm.sync.pulled",
        run.realm,
        changed=run.changed,
        artifacts=len(artifacts),
    )
    return result


def _overwrite_generic_families(artifacts: list[RealmSyncArtifact], *, realm: Realm) -> bool:
    """The generic overwrite loop: every artifact with a destination (only the
    store-record families have one — ``families.SYNC_PATH_FAMILIES``)."""

    changed = False
    for artifact in artifacts:
        artifact.destination.parent.mkdir(parents=True, exist_ok=True)
        before = artifact.destination.read_bytes() if artifact.destination.exists() else None
        data = _pulled_artifact_bytes(artifact, realm=realm)
        # Compare canonically so a CRLF local store file vs an LF published
        # artifact is not mistaken for a change (the JSON parses identically);
        # only a real content edit rewrites the destination and flags changed.
        if before is None or _canonicalize_text_bytes(before) != _canonicalize_text_bytes(data):
            artifact.destination.write_bytes(data)
            changed = True
    return changed


@dataclass
class _PullRun:
    """One pull's working state, handed to every applier in turn: the realm
    record the appliers decide against (re-read by the skill lane, see
    ``_pull_skill_inbox``), the pulled subtree, and each applier's summary."""

    realm: Realm
    subtree: Path
    changed: bool = False
    board: Any = None
    office: Any = None
    level: Any = None
    map: Any = None
    skill: Any = None
    skill_tombstones: dict[str, list] | None = None
    persona: Any = None
    profile_files: Any = None
    instance: Any = None
    flow_graph: Any = None
    workspace_tombstones: dict[str, list] | None = None


class PullApplier(NamedTuple):
    """One family's pull: ``apply`` records its summary on the run and answers
    whether it changed anything."""

    name: str
    apply: Callable[[_PullRun], bool]


def _pull_boards(run: _PullRun) -> bool:
    # Mission Board: board card files are excluded from the generic overwrite
    # loop (_destination_for_sync_path returns None for store/boards/*); apply
    # the per-card LWW decision table + baseline + conflict sidecars here.
    from ..board_sync import apply_board_pull

    run.board = apply_board_pull(run.realm.id, run.subtree)
    return bool(run.board.adopted or run.board.converged or run.board.archived)


def _pull_office(run: _PullRun) -> bool:
    # Mission Office: same exclusion (store/office/*), same shape — the
    # per-actor 3-way baseline merge owns the office pull (plan §5).
    from ..office_sync import apply_office_pull

    run.office = apply_office_pull(run.realm.id, run.subtree)
    return bool(run.office.adopted or run.office.converged or run.office.archived)


def _pull_level(run: _PullRun) -> bool:
    # The workspace LEVEL: same exclusion (store/levels/* ->
    # _destination_for_sync_path None), same whole-document 3-way shape as the
    # canvas. It stands HERE — after the generic loop that materialized
    # store/workspaces/*, beside the office rather than inside its ordering
    # argument — because R7 rules a level the ENVIRONMENT and the office's
    # actors the CONTENTS placed on it, stored separately and never merged, so
    # neither applier reads the other's files and there is no order between them
    # to get wrong. What there IS an order against is the workspace records
    # above: a level is addressed BY a workspace.
    from ..level_sync import apply_level_pull

    run.level = apply_level_pull(run.realm.id, run.subtree)
    return bool(run.level.changed)


def _pull_map(run: _PullRun) -> bool:
    # The MAP CATALOGUE: same exclusion (store/maps/* ->
    # _destination_for_sync_path None), same whole-document 3-way shape. It has
    # no ordering argument against the workspace records — a map is addressed by
    # a MAP ID, not by a workspace — and none against the level pull either:
    # neither applier reads the other's files. The level's sidecar names a map
    # id and resolving that id to a display name is the LAUNCHER's step, after
    # both families have landed.
    from ..map_sync import apply_map_pull

    run.map = apply_map_pull(run.realm.id, run.subtree)
    return bool(run.map.changed)


def _pull_skill_inbox(run: _PullRun) -> bool:
    # Realm skills: excluded from the generic loop too (skills/* →
    # _destination_for_sync_path None). Mirror them into the resolver-invisible
    # per-realm inbox and admit them to the canonical root only through the one
    # guarded promotion door (auto-adopt new, converge identical, hold divergent).
    # Re-read first: the overwrite loop above may have replaced the realm record
    # with the publisher's snapshot, so the skill lane must decide against the
    # ledger that just ARRIVED, not the one this pull started with (the same
    # reason ``_apply_workspace_tombstones`` re-reads). Every use of the realm
    # after this — sidecar, result, event — wants the pulled record too.
    run.realm = RealmStore().get(run.realm.id)
    run.skill = apply_skill_inbox_pull(run.realm, run.subtree)
    return bool(run.skill.adopted or run.skill.updated or run.skill.removed or run.skill.tombstoned)


def _pull_skill_tombstones(run: _PullRun) -> bool:
    # Skill deletions: archive the local canonical copy of anything the pulled
    # ledger blocks. AFTER the inbox applier (the archive must not race the
    # promotion loop's occupancy guard) and BEFORE install_harness_skills (a
    # no-op for tombstonable slugs, but the order is the argument).
    run.skill_tombstones = _apply_skill_tombstones(run.realm)
    return bool(run.skill_tombstones["archived"])


def _pull_persona_config(run: _PullRun) -> bool:
    # Persona definitions: excluded from the generic loop too
    # (profiles/<name>/config.yaml → _destination_for_sync_path None). The member's
    # config is merged key-wise against a never-synced baseline — the realm owns
    # the shared persona surface, the member keeps every machine section they
    # authored, and divergent definitions are HELD, never clobbered.
    from ..persona_config_sync import apply_persona_config_pull

    run.persona = apply_persona_config_pull(run.realm.id, run.subtree)
    return bool(run.persona.changed)


def _pull_profile_files(run: _PullRun) -> bool:
    # Profile FILES (MEMORY.md, core context, persona prompts): excluded from the
    # generic loop too (``profiles/*`` and ``store/profile_files/*`` →
    # ``_destination_for_sync_path`` None). These were the last four kinds still
    # overwritten wholesale — a member's accumulated MEMORY.md included. The lane
    # merges per DESTINATION against a never-synced baseline: adopt when the
    # member has nothing (or an untouched copy), converge when identical, HOLD
    # whenever their content diverged, and never delete.
    from ..profile_artifact_sync import apply_profile_artifact_pull

    run.profile_files = apply_profile_artifact_pull(run.realm.id, run.subtree)
    return bool(run.profile_files.changed)


def _pull_persona_instances(run: _PullRun) -> bool:
    # Persona INSTANCES — THE mint door. A pulled desk whose agent does not exist
    # on this machine gets one (the operator's 2026-08-31 ruling; the
    # instance-replication plan §3.1). Excluded from the generic loop like every
    # other family here (``store/persona_instances.yaml`` →
    # ``_destination_for_sync_path`` None), because the write is a STORE door —
    # a raw file write would produce a replica no live consumer ever hears about.
    from ..persona_instance_sync import apply_persona_instance_pull

    # §5.2 retire-follows-the-DESK: the actor keys the OFFICE lane archived in
    # THIS pull. Taken from the office summary's own outcomes rather than
    # re-derived, because only that arm knows which archives it actually took —
    # the ones it FENCED (``delete_fenced``, an unreadable remote) and the ones
    # it tried and could not are both absent from this list by construction, and
    # retiring an agent for a desk removal that did not happen is the worst
    # mistake available in this lane.
    desks_removed = [
        row["actor_key"]
        for row in (run.office.archive_outcomes or [])
        if row.get("outcome") == "archived" and row.get("actor_key")
    ]
    run.instance = apply_persona_instance_pull(
        run.realm.id, run.subtree, desks_removed=desks_removed
    )
    return bool(run.instance.changed)


def _pull_flow_graphs(run: _PullRun) -> bool:
    # The CANVAS, immediately AFTER the mint door and never before it. Owner
    # liveness is what decides whether a stored canvas is an operator's drawing
    # or an orphan addressed to an agent that no longer exists, so a canvas that
    # lands before its owner is minted is indistinguishable from garbage — and
    # the pull's own ``unbound_node_agents`` accounting would name every binding
    # this same pass was about to satisfy. The ordering is pinned by a test.
    from ..flow_graph_sync import apply_flow_graph_pull

    run.flow_graph = apply_flow_graph_pull(run.realm.id, run.subtree)
    return bool(run.flow_graph.changed)


def _pull_workspace_tombstones(run: _PullRun) -> bool:
    # Workspace deletions: honor the pulled realm's deleted_workspace_ids
    # resurrection-guard ledger so a member's surviving local copy neither
    # lingers nor republishes a workspace another member deleted.
    run.workspace_tombstones = _apply_workspace_tombstones(run.realm.id)
    return bool(run.workspace_tombstones["deleted"] or run.workspace_tombstones["archived"])


#: Every applier a pull runs after the generic overwrite loop, IN ORDER — and the
#: order is the argument, not a preference. The persona-definition and
#: profile-file lanes run before the instance mint, because the mint reads the
#: definition to derive ``role``/``profile_id`` and a mint from a definition that
#: has not landed yet builds the wrong agent. The mint runs before the canvas
#: (owner liveness decides what a canvas is) and before the workspace tombstone
#: lane, so a replica is never minted into a workspace this same pull is about
#: to archive. ``pull_realm_sync`` iterates this and nothing else.
PULL_APPLIERS: Final[tuple[PullApplier, ...]] = (
    PullApplier("board_sync", _pull_boards),
    PullApplier("office_sync", _pull_office),
    PullApplier("level_sync", _pull_level),
    PullApplier("map_sync", _pull_map),
    PullApplier("skill_sync", _pull_skill_inbox),
    PullApplier("skill_tombstones", _pull_skill_tombstones),
    PullApplier("persona_config_sync", _pull_persona_config),
    PullApplier("profile_artifact_sync", _pull_profile_files),
    PullApplier("persona_instance_sync", _pull_persona_instances),
    PullApplier("flow_graph_sync", _pull_flow_graphs),
    PullApplier("workspace_tombstones", _pull_workspace_tombstones),
)


def _pull_accounting(run: _PullRun, install_results: list[Any]) -> dict[str, Any]:
    """The pull envelope's family rows, in the order the launcher has always read them."""

    rows: dict[str, Any] = {
        "board_sync": run.board.as_dict(),
        "office_sync": run.office.as_dict(),
        "skill_sync": run.skill.as_dict(),
        # Emitted UNCONDITIONALLY for the reason the two rows below are: an
        # omitted key cannot tell "this realm publishes no level" apart from
        # "this ack came from a hermes with no level family", and the launcher's
        # version-skew rule (L1/L2) has to tell those two apart. ``source: null``
        # inside it is the first of those.
        "level_sync": run.level.as_dict(),
        # Unconditional for the key above it's reason, and the launcher's adapter
        # reads it the same way: ``source: null`` says "this peer runs a hermes
        # with no map family", which is the one case where a missing catalogue
        # entry is expected rather than a defect.
        "map_sync": run.map.as_dict(),
        "profile_artifact_sync": run.profile_files.as_dict(),
        # THE contract seam with the launcher (plan §6). Emitted UNCONDITIONALLY,
        # carrying ``source: null`` when the peer published no projection,
        # because the launcher's version-skew rule (L1/L2) has to tell "this peer
        # runs an older hermes" apart from "this ack came from an older hermes"
        # — and an omitted key cannot say the first one.
        "persona_instance_sync": run.instance.as_dict(),
        # Emitted UNCONDITIONALLY for the same reason as the row above: an
        # omitted key cannot tell "this peer publishes no canvas" apart from
        # "this ack came from a hermes that has no canvas family", and the
        # launcher's skew rule needs both.
        "flow_graph_sync": run.flow_graph.as_dict(),
    }
    tombstones = run.workspace_tombstones
    if tombstones["deleted"] or tombstones["archived"] or tombstones["warnings"]:
        rows["workspace_tombstones"] = tombstones
    if any(run.skill_tombstones.values()):
        rows["skill_tombstones"] = run.skill_tombstones
    # ``profile_sync`` carries the W-H4 rows (which profile homes this pull
    # touched/materialized) PLUS the persona-definition merge accounting PLUS the
    # profile-FILE merge accounting. Emitted whenever any half has something to
    # say — a realm that publishes persona definitions but no per-profile files
    # must still report its merge, and vice versa.
    if run.profile_files.source is not None or run.persona.source is not None:
        rows["profile_sync"] = {
            "profiles": sorted(set(run.profile_files.profiles)),
            "created": sorted(set(run.profile_files.created_profiles)),
            "personas": run.persona.as_dict(),
            "files": run.profile_files.as_dict(),
        }
    rows["skill_reconcile"] = {
        "installed": [item.skill for item in install_results],
        "changed": [item.skill for item in install_results if item.changed],
        "ok": all(item.ok for item in install_results),
    }
    return rows


def _apply_workspace_tombstones(realm_id: str) -> dict[str, list]:
    """Apply the realm's ``deleted_workspace_ids`` ledger after a pull.

    A workspace another member deleted must not survive here as a live copy —
    it would ride this member's next publish straight back into the realm.
    Hard-delete the local copy through the store chokepoint (cascade + event);
    a copy that still owns local live-store goals degrades to ARCHIVE instead
    (evidence is never destroyed by a sync), reported as a warning.
    """
    summary: dict[str, list] = {"deleted": [], "archived": [], "warnings": []}
    try:
        realm = RealmStore().get(realm_id)  # re-read: the pull may have rewritten it
    except Exception:  # noqa: BLE001 — no realm, nothing to reconcile
        return summary
    ledger = list(getattr(realm, "deleted_workspace_ids", None) or [])
    if not ledger:
        return summary
    from ..errors import WorkspaceDeleteBlocked
    from ..store import WorkspaceStore as _WorkspaceStore

    store = _WorkspaceStore()
    for workspace_id in ledger:
        if not paths.workspace_path(workspace_id).exists():
            continue
        try:
            store.delete(workspace_id, reason="realm_sync_tombstone")
            summary["deleted"].append(workspace_id)
        except WorkspaceDeleteBlocked as exc:
            try:
                workspace = store.get(workspace_id)
                if not workspace.archived:
                    store.archive(workspace_id)
                summary["archived"].append(workspace_id)
                summary["warnings"].append(
                    {
                        "code": "workspace_tombstone_archived",
                        "workspace_id": workspace_id,
                        "message": f"Deleted in realm but kept archived here: {exc}",
                    }
                )
            except Exception as inner:  # noqa: BLE001 — accounted, never silent
                summary["warnings"].append(
                    {"code": "workspace_tombstone_failed", "workspace_id": workspace_id, "message": str(inner)}
                )
        except Exception as exc:  # noqa: BLE001 — accounted, never silent
            summary["warnings"].append(
                {"code": "workspace_tombstone_failed", "workspace_id": workspace_id, "message": str(exc)}
            )
    return summary


def _apply_skill_tombstones(realm: Realm) -> dict[str, list]:
    """Apply the realm's ``skill_tombstones`` ledger to the CANONICAL root.

    The workspace twin one function up, with one deliberate difference: this
    lane ARCHIVES where that one hard-deletes. ``shared/skills`` is governed by
    the promotion door's standing "never delete — archive" invariant, and a
    skill package is always operator/agent-authored content — i.e. always
    evidence — so the displaced copy moves to ``.archive/<UTC ts>/<slug>``
    (resolver- and publish-invisible) instead of going away. That also makes
    restore-with-content a two-step operator verb (un-tombstone + promote from
    the archive) rather than a data-recovery incident.

    Packages are matched through ``skill_tombstoned``, the same rule the mirror
    and the publish filter ask, so "deleted" means one thing in all three
    places. ``CANONICAL_SHARED_SKILL_IDS`` are skipped with a warning rather
    than archived: the installer re-copies them from repo source on the very
    same pull, so archiving one would be undone within the same verb — belt to
    the store chokepoint's suspenders, for a ledger written by a peer that did
    not enforce it. Per-slug isolation: one failed archive is a typed warning
    row, never an aborted pull.

    ``realm`` must be the PULLED record (see ``pull_realm_sync``'s re-read).
    """

    summary: dict[str, list] = {"archived": [], "skipped_installer_owned": [], "warnings": []}
    if not (getattr(realm, "skill_tombstones", None) or []):
        return summary
    root = get_shared_skills_dir()
    if not root.exists():
        return summary

    from agent_runtime.profile_home import CANONICAL_SHARED_SKILL_IDS

    from ..skill_promotion import _archive_package

    # Materialized before the first move: the walk reads the directory the
    # archive step is about to mutate.
    for slug, package_dir in list(_iter_publishable_skill_packages(root)):
        if skill_tombstoned(realm, slug) is None:
            continue
        if slug in CANONICAL_SHARED_SKILL_IDS:
            summary["skipped_installer_owned"].append(slug)
            summary["warnings"].append(
                {
                    "code": "skill_tombstone_installer_owned",
                    "skill": slug,
                    "message": (
                        "Tombstoned in the realm but hermes-installed here; the "
                        "installer re-copies it from repo source on every pull, so "
                        "the local package is left intact."
                    ),
                }
            )
            continue
        try:
            _archive_package(package_dir, slug)
            summary["archived"].append(slug)
        except Exception as exc:  # noqa: BLE001 — accounted, never silent
            summary["warnings"].append(
                {"code": "skill_tombstone_failed", "skill": slug, "message": str(exc)}
            )
    # The ``.provenance/<slug>.json`` sidecar is deliberately left in place:
    # provenance is history (what was promoted, from where), not liveness, and a
    # later promotion of the same slug overwrites it.
    return summary


def _pulled_artifact_bytes(artifact: RealmSyncArtifact, *, realm: Realm) -> bytes:
    """Reconcile the incoming realm JSON with local truth during a Git pull.

    Two reconciliations, deliberately scoped differently:

    1. **Authority fields** (server-bound realms only). The realm JSON is shared
       so workspace membership can travel through Git, but a server-bound
       realm's identity/default pointer is authoritative from backend adoption.
       An older repo snapshot must never roll that pointer back.
    2. **Resurrection-guard ledgers** (every realm). ``skill_tombstones`` and
       ``deleted_workspace_ids`` are UNIONED rather than adopted, so a
       concurrent publish cannot drop a delete another member recorded (RD-11).
       Not gated on ``server_id``: a local-only realm with a sync repo loses a
       tombstone exactly the same way, and the guard is not about identity.

    Returns the source bytes UNTOUCHED when neither reconciliation changes
    anything, so a pull that reconciles nothing cannot report ``changed`` on
    re-serialization alone.
    """
    data = artifact.source.read_bytes()
    if artifact.kind != SyncFamily.REALM or not artifact.destination.exists():
        return data
    try:
        incoming = json.loads(data.decode("utf-8"))
        current = json.loads(artifact.destination.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return data
    if not isinstance(incoming, dict) or not isinstance(current, dict):
        return data
    merged = dict(incoming)
    if realm.server_id:
        for field in _REALM_AUTHORITY_FIELDS:
            if field in current:
                merged[field] = current[field]
    mergers = {
        "skill_tombstones": merge_skill_tombstone_ledgers,
        "workspace_lifts": merge_workspace_lift_ledgers,
        # Reads the lift register merged one iteration earlier — the tuple's
        # order is what guarantees it is there. Falls back to the incoming and
        # local rows so the subtraction is still right if either side is the
        # only one carrying a lift.
        "deleted_workspace_ids": lambda local_rows, incoming_rows: (
            merge_deleted_workspace_ledgers(
                local_rows,
                incoming_rows,
                lifts=merged.get("workspace_lifts"),
            )
        ),
    }
    for field in _UNIONED_REALM_LEDGERS:
        if not (current.get(field) or incoming.get(field)):
            # Both empty or absent: nothing to union, and inventing the key
            # would rewrite an old member's record for no gain.
            continue
        merged[field] = mergers[field](current.get(field), incoming.get(field))
    if merged == incoming:
        return data
    return json.dumps(merged, indent=2, sort_keys=True, default=str).encode("utf-8")


def _assert_no_secret_artifacts(artifacts: list[RealmSyncArtifact]) -> None:
    blocked: list[str] = []
    for artifact in artifacts:
        rel = artifact.relative_path.replace("\\", "/")
        if _is_secretish_path(rel) or _is_hard_excluded_path(rel) or _artifact_contains_secret_assignment(artifact):
            blocked.append(rel)
    if blocked:
        raise RealmSyncError("sync_secret_excluded", "Realm sync refused to include excluded secret/state artifacts.", safe_details={"paths": blocked[:20]})


def _artifact_contains_secret_assignment(artifact: RealmSyncArtifact) -> bool:
    """Scan what actually publishes.

    A synthesized artifact must be scanned by its CONTENT — scanning its
    provenance ``source`` would test a file whose secrets the projection already
    filtered out, and (worse) could refuse a publish over a secret that never
    leaves the machine. The secret-exclusion path itself is unchanged.
    """

    if artifact.content is not None:
        return bool(SECRET_ASSIGNMENT_RE.search(artifact.content.decode("utf-8", errors="ignore")))
    return _file_contains_secret_assignment(artifact.source)


def _file_contains_secret_assignment(path: Path) -> bool:
    try:
        if path.stat().st_size > 1_000_000:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(SECRET_ASSIGNMENT_RE.search(text))
