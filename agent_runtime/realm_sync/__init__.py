"""Realm sync — the package map (program rule 16).

Entry points (what calls in):

* ``status.realm_sync_status``, ``publish.publish_realm_sync``,
  ``pull.pull_realm_sync`` — the three verbs ``harness_parts/realm_commands``
  wires; ``realm_revert`` reads the drift rows and the repo helpers.
* ``sidecar.read_realm_sync_sidecar`` — the only surface ``build_snapshot`` and
  ``skills_inventory`` may read (zero git, zero artifact resolution).
* ``models`` / ``families`` — what ``realm_membership``, ``sync_admission`` and
  ``profile_artifact_sync`` import back; neither imports an applier, so the
  lazy cycles with the per-family appliers stay lazy.

Modules, lowest layer first (no module imports one above it — W0-G6):

=================  ======  =====================================================
module             layer   owns
=================  ======  =====================================================
models             models  ``RealmSyncError``, ``RealmSyncArtifact``, membership
                           boundary, secret/state path sets, the LF pin
families           policy  ``SyncFamily`` (the ONE family vocabulary) and
                           ``SYNC_PATH_FAMILIES`` (path -> family, kind,
                           generic destination, owning applier); the
                           profile-file destination vocabulary; secret /
                           hard-excluded predicates
ledgers            policy  the RD-11 ledger unions and the tombstone receipt rows
git                stores  authorization, the sync repo, ``_git`` (over
                           ``agent_runtime.git_cmd.run_git``), redaction
publish_scans      stores  the board / office / level / map one-pass scans
persona_artifacts  stores  profile files, the three synthesized projections,
                           the base-seed and portability guards
artifacts          stores  ``_resolve_artifacts_with_projection`` — the ONE
                           "what does this realm publish" pass; skill packages
drift              stores  ``DRIFT_WALKS`` -> ``store_drift_items`` and the
                           counts derived from its rows
sidecar            stores  status sidecar, manifest, timestamps, sync events
skill_inbox        lanes   the pull's skill lane: mirror, then admit each package
pull               lanes   ``pull_realm_sync`` over ``PULL_APPLIERS`` (ORDER is
                           the argument); the secret scan both verbs run
publish            lanes   ``publish_realm_sync`` and ``BASELINE_FAMILIES``
status             lanes   ``realm_sync_status``
=================  ======  =====================================================

Stores written: the realm sync git repo (``git``), ``realm_sync_state/``
(``sidecar``), the per-family baselines (through each applier), the skills
inbox (``skill_inbox``), the event log (``sidecar``). The per-family appliers
(``board_sync``, ``office_sync``, ``level_sync``, ``map_sync``,
``persona_config_sync``, ``persona_instance_sync``, ``flow_graph_sync``,
``profile_artifact_sync``, ``skill_promotion``) are imported LAZILY, inside the
function that calls them, and must stay that way.

Re-exported below: every public name, plus each private name a module outside
this package imports today, so no importer's path changed with the split.
"""

from __future__ import annotations

from agent_runtime.realm_sync.models import (
    BASE_PROFILE_NAME,
    HARD_EXCLUDED_PATH_PARTS,
    MembershipDecision,
    RealmMembershipProvider,
    RealmSyncArtifact,
    RealmSyncError,
    SECRET_PATH_MARKERS,
    _canonicalize_text_bytes,
    _safe_display_path,
)
from agent_runtime.realm_sync.families import (
    GENERIC_PULL,
    SYNC_PATH_FAMILIES,
    SyncFamily,
    SyncPathFamily,
    _destination_for_sync_path,
    _is_hard_excluded_path,
    _is_secretish_path,
    _kind_for_sync_path,
)
from agent_runtime.realm_sync.ledgers import (
    merge_deleted_workspace_ledgers,
    merge_skill_tombstone_ledgers,
    merge_workspace_lift_ledgers,
    skill_tombstone_rows,
)
from agent_runtime.realm_sync.git import (
    _git,
    _git_clone,
    _realm_subtree,
    _redact_text,
    _sync_repo_path,
)
from agent_runtime.realm_sync.publish_scans import (
    BoardPublishScan,
    LevelPublishScan,
    MapPublishScan,
    OfficePublishScan,
    _office_publish_scan,
)
from agent_runtime.realm_sync.persona_artifacts import (
    _assert_no_raw_profile_config,
    _assert_portable_artifacts,
    _flow_graph_row,
    _office_wanted_persona_ids,
    _persona_artifacts,
    _persona_instance_row,
)
from agent_runtime.realm_sync.artifacts import (
    _resolve_artifacts_with_projection,
    _workspaces_for_realm,
    publishable_skill_packages,
    realm_agent_selection_state,
    resolve_realm_sync_artifacts,
    sync_artifacts_for_workspace_agent,
)
from agent_runtime.realm_sync.drift import (
    DRIFT_FAMILY_BOARD,
    DRIFT_FAMILY_BOARD_CARD,
    DRIFT_FAMILY_FLOW_GRAPH,
    DRIFT_FAMILY_OFFICE_ACTOR,
    DRIFT_FAMILY_OFFICE_SURFACE,
    DRIFT_FAMILY_PERSONA_INSTANCE,
    DRIFT_FAMILY_SKILL,
    DRIFT_KEY_BOARD_DEF,
    DRIFT_KEY_OFFICE_SURFACE,
    DRIFT_KIND_ADDED,
    DRIFT_KIND_CHANGED,
    DRIFT_KIND_REMOVED,
    DRIFT_WALKS,
    StoreDriftItem,
    _PERSONA_INSTANCE_DRIFT_COUNTS,
    _any_store_drift,
    _board_store_drift,
    _drift_counts,
    _office_store_drift,
    _persona_instance_store_drift_items,
    store_drift_items,
)
from agent_runtime.realm_sync.sidecar import (
    _append_realm_sync_event,
    read_realm_sync_sidecar,
    realm_sync_sidecar_path,
)
from agent_runtime.realm_sync.skill_inbox import (
    SkillSyncSummary,
    _held_skill_packages_for_realm,
    _mirror_realm_skill_inbox,
    apply_skill_inbox_pull,
)
from agent_runtime.realm_sync.pull import (
    PULL_APPLIERS,
    PullApplier,
    _apply_workspace_tombstones,
    _assert_no_secret_artifacts,
    pull_realm_sync,
)
from agent_runtime.realm_sync.publish import (
    BASELINE_FAMILIES,
    publish_realm_sync,
)
from agent_runtime.realm_sync.status import (
    _flow_graph_status_row,
    realm_sync_status,
)

__layer__ = "lanes"
__all__ = [
    "BASELINE_FAMILIES",
    "BASE_PROFILE_NAME",
    "BoardPublishScan",
    "DRIFT_FAMILY_BOARD",
    "DRIFT_FAMILY_BOARD_CARD",
    "DRIFT_FAMILY_FLOW_GRAPH",
    "DRIFT_FAMILY_OFFICE_ACTOR",
    "DRIFT_FAMILY_OFFICE_SURFACE",
    "DRIFT_FAMILY_PERSONA_INSTANCE",
    "DRIFT_FAMILY_SKILL",
    "DRIFT_KEY_BOARD_DEF",
    "DRIFT_KEY_OFFICE_SURFACE",
    "DRIFT_KIND_ADDED",
    "DRIFT_KIND_CHANGED",
    "DRIFT_KIND_REMOVED",
    "DRIFT_WALKS",
    "GENERIC_PULL",
    "HARD_EXCLUDED_PATH_PARTS",
    "LevelPublishScan",
    "MapPublishScan",
    "MembershipDecision",
    "OfficePublishScan",
    "PULL_APPLIERS",
    "PullApplier",
    "RealmMembershipProvider",
    "RealmSyncArtifact",
    "RealmSyncError",
    "SECRET_PATH_MARKERS",
    "SYNC_PATH_FAMILIES",
    "SkillSyncSummary",
    "StoreDriftItem",
    "SyncFamily",
    "SyncPathFamily",
    "_PERSONA_INSTANCE_DRIFT_COUNTS",
    "_any_store_drift",
    "_append_realm_sync_event",
    "_apply_workspace_tombstones",
    "_assert_no_raw_profile_config",
    "_assert_no_secret_artifacts",
    "_assert_portable_artifacts",
    "_board_store_drift",
    "_canonicalize_text_bytes",
    "_destination_for_sync_path",
    "_drift_counts",
    "_flow_graph_row",
    "_flow_graph_status_row",
    "_git",
    "_git_clone",
    "_held_skill_packages_for_realm",
    "_is_hard_excluded_path",
    "_is_secretish_path",
    "_kind_for_sync_path",
    "_mirror_realm_skill_inbox",
    "_office_publish_scan",
    "_office_store_drift",
    "_office_wanted_persona_ids",
    "_persona_artifacts",
    "_persona_instance_row",
    "_persona_instance_store_drift_items",
    "_realm_subtree",
    "_redact_text",
    "_resolve_artifacts_with_projection",
    "_safe_display_path",
    "_sync_repo_path",
    "_workspaces_for_realm",
    "apply_skill_inbox_pull",
    "merge_deleted_workspace_ledgers",
    "merge_skill_tombstone_ledgers",
    "merge_workspace_lift_ledgers",
    "publish_realm_sync",
    "publishable_skill_packages",
    "pull_realm_sync",
    "read_realm_sync_sidecar",
    "realm_agent_selection_state",
    "realm_sync_sidecar_path",
    "realm_sync_status",
    "resolve_realm_sync_artifacts",
    "skill_tombstone_rows",
    "store_drift_items",
    "sync_artifacts_for_workspace_agent",
]
