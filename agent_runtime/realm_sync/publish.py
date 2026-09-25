"""``publish_realm_sync``: write the realm subtree, push, then record every family's baseline."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from ..realm_membership import RealmSyncCredential

from .. import paths
from ..models import Realm
from ..store import RealmStore, skill_tombstoned
from .models import (
    RealmMembershipProvider,
    RealmSyncArtifact,
    RealmSyncError,
    _canonicalize_text_bytes,
)
from .git import (
    _authorize,
    _credential_git_config,
    _ensure_git_identity,
    _ensure_sync_repo,
    _git,
    _git_state,
    _realm_subtree,
    _refresh_remote_tracking,
)
from .persona_artifacts import (
    _assert_no_raw_profile_config,
    _assert_portable_artifacts,
    _flow_graph_row,
    _persona_instance_row,
    _persona_projection_row,
    _profile_files_row,
    _published_profile_file_hashes,
)
from .families import SyncFamily
from .artifacts import _ResolvedPublish, _resolve_artifacts_with_projection, publishable_skill_packages
from .sidecar import (
    _append_realm_sync_event,
    _sync_result,
    _write_sync_metadata,
    _write_sync_sidecar,
    _write_timestamp,
)
from .skill_inbox import _held_skill_packages_for_realm, _mirror_realm_skill_inbox
from .pull import _assert_no_secret_artifacts

logger = logging.getLogger(__name__)

__layer__ = "lanes"
__all__ = [
    "BASELINE_FAMILIES",
    "_notify_publish",
    "_publish_accounting",
    "_published_artifacts_differ",
    "_published_row",
    "_record_board_baseline",
    "_record_flow_graph_baseline",
    "_record_level_baseline",
    "_record_map_baseline",
    "_record_office_baseline",
    "_record_persona_config_baseline",
    "_record_persona_instance_baseline",
    "_record_profile_files_baseline",
    "_record_publish_baselines",
    "_record_skill_publish_baseline",
    "_stage_commit_and_push",
    "publish_realm_sync",
]


def publish_realm_sync(
    realm_id: str,
    *,
    dry_run: bool = False,
    membership: RealmMembershipProvider | None = None,
    credential: "RealmSyncCredential | None" = None,
) -> dict[str, Any]:
    """Publish this realm: stage the subtree, commit and push, record every
    family's baseline, account. Each phase is its own function below."""

    realm = RealmStore().get(realm_id)
    _authorize(realm, "publish", membership, credential)
    repo = _ensure_sync_repo(realm, credential=credential)
    # Same fetch-first discipline as the status path: the ``sync_behind``
    # refusal below is only honest against a refreshed ``@{u}``. Without it a
    # remote-side change surfaced here as a failed push (mislabeled
    # ``sync_remote_unreachable``) instead of the typed pull-first refusal.
    # Best-effort — an unreachable remote falls through to the push's own error.
    _refresh_remote_tracking(repo, credential=credential)
    git = _git_state(repo)
    if git["conflicts"]:
        raise RealmSyncError("sync_conflict", "Realm sync repo has unresolved git conflicts.", safe_details={"conflicts": git["conflicts"]})
    if git["behind"] > 0:
        raise RealmSyncError("sync_behind", "Realm sync repo is behind its upstream; pull before publishing.", retryable=True, safe_details={"behind": git["behind"]})
    resolved = _resolve_artifacts_with_projection(realm_id)
    artifacts = resolved.artifacts
    _assert_no_secret_artifacts(artifacts)
    _assert_no_raw_profile_config(artifacts)
    _assert_portable_artifacts(artifacts)
    if dry_run:
        result = _sync_result(realm, "publish", "dry_run", artifacts, repo=repo, git=git, changed=False)
        result.update(_publish_accounting(resolved))
        return result

    subtree = _realm_subtree(repo, realm.id)
    changed = _stage_commit_and_push(realm, repo=repo, subtree=subtree, artifacts=artifacts, credential=credential)
    _write_timestamp(repo, "last_publish.txt")
    receipts = _record_publish_baselines(realm, resolved)
    # The SKILL family: the same baseline discipline as every family in
    # ``BASELINE_FAMILIES``, plus one step none of them needs. The skill lane
    # decides against a MIRROR of the realm (the per-realm inbox), not against
    # the subtree directly, so recording the baseline alone is not enough — the
    # inbox still holds the PRE-publish realm copy, and ``skills_drift`` computed
    # from it reports my own just-shipped edit as a conflict. That is precisely
    # what the operator measured on 2026-09-12: "Published realm 'test realm' ·
    # just now" with the SKILLS HELD card still naming the package they had just
    # published. After a successful push the subtree IS the realm, so the inbox
    # is re-mirrored from it — and only then is ``skills_drift`` recomputed, by
    # the sidecar write at the end of this function.
    _record_skill_publish_baseline(realm, subtree=subtree)
    warnings = _notify_publish(realm, repo=repo, artifacts=artifacts, credential=credential) if changed else []
    git_after = _git_state(repo)
    result = _sync_result(realm, "publish", "published", artifacts, repo=repo, git=git_after, changed=changed)
    result.update(
        _publish_accounting(
            resolved,
            office_baseline=receipts.get(SyncFamily.OFFICE) or {"recorded": [], "refused": []},
        )
    )
    if warnings:
        result["warnings"] = warnings
    _write_sync_sidecar(realm, repo=repo, git=git_after, skills_drift=_held_skill_packages_for_realm(realm), artifacts=artifacts)
    _append_realm_sync_event(
        "realm.sync.published",
        realm,
        changed=changed,
        artifacts=len(artifacts),
    )
    return result


def _stage_commit_and_push(
    realm: Realm,
    *,
    repo: Path,
    subtree: Path,
    artifacts: list[RealmSyncArtifact],
    credential: "RealmSyncCredential | None",
) -> bool:
    """Rewrite the realm subtree when its canonical bytes changed, then commit and
    push. Returns whether a commit was made."""

    subtree_rel = f"realms/{paths.safe_path_token(realm.id)}"
    # Canonicalize every published artifact to LF at this single write/copy
    # chokepoint (binary assets pass through untouched — see
    # ``_canonicalize_text_bytes``). The store lane writes CRLF on Windows while
    # the pull lane writes LF; copying those raw bytes made every publish a
    # whole-file EOL churn and reported changed=true on no-op runs.
    desired = {
        artifact.relative_path.replace("\\", "/"): _canonicalize_text_bytes(artifact.read_bytes())
        for artifact in artifacts
    }
    # Content-aware change detection: only (re)write the subtree when the
    # canonical artifact bytes actually differ from what is already published.
    # manifest.json is excluded from this comparison because it carries a
    # volatile generated_at — a timestamp-only rewrite is never a real change.
    content_changed = _published_artifacts_differ(subtree, desired)
    # The repo-root .gitattributes is materialized at the ensure chokepoint; make
    # sure a newly-introduced one still rides this publish even when no artifact
    # changed. It is never an artifact, so it skips the manifest + secret scan.
    # Only stage .gitattributes when it actually exists — its write is
    # best-effort, and ``git add`` errors on a pathspec that matches nothing.
    add_paths = [subtree_rel]
    if (repo / ".gitattributes").exists():
        add_paths.append(".gitattributes")
    gitattributes_pending = ".gitattributes" in add_paths and bool(
        _git(repo, "status", "--porcelain", "--", ".gitattributes").strip()
    )
    if content_changed:
        if subtree.exists():
            shutil.rmtree(subtree)
        for artifact in artifacts:
            target = subtree / artifact.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(desired[artifact.relative_path.replace("\\", "/")])
        _write_sync_metadata(subtree, realm=realm, artifacts=artifacts)
    if not (content_changed or gitattributes_pending):
        return False
    _git(repo, "add", "--", *add_paths)
    changed = bool(_git(repo, "status", "--porcelain", "--", *add_paths).strip())
    if changed:
        _ensure_git_identity(repo)
        _git(repo, "commit", "-m", f"Publish realm sync {realm.id}")
        try:
            _git(repo, "push", extra_config=_credential_git_config(credential))
        except RealmSyncError as exc:
            raise RealmSyncError("sync_remote_unreachable", "Realm sync publish committed locally but could not push upstream.", retryable=True, safe_details=exc.safe_details) from exc
    return changed


def _publish_accounting(resolved: _ResolvedPublish, *, office_baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """The publish envelope's family rows. ``office_baseline`` is ``None`` on a
    dry run, and that is the only difference between the two shapes: a dry run
    records no baseline and publishes nothing, so it carries neither the office
    ``baseline`` receipt nor the level/map ``published`` lists."""

    published = office_baseline is not None
    rows: dict[str, Any] = {
        "persona_projection": _persona_projection_row(resolved.projection, resolved.bound_profiles),
        "profile_files": _profile_files_row(resolved.artifacts, resolved.profile_files_withheld),
    }
    # Additive publish accounting for the office family: which workspaces did
    # not travel at all and why, and which of the ones that did got their
    # baseline recorded. A workspace that publishes nothing because a file would
    # not decode is a fact the operator must be able to READ — the alternative,
    # a quiet partial publish, is what turns one quarantined file here into desk
    # removals on every peer.
    rows["office_sync"] = {"refused": list(resolved.office_refused or [])}
    if published:
        rows["office_sync"]["baseline"] = office_baseline
    rows["board_sync"] = {"refused": list(resolved.board_refused or [])}
    # Additive, and emitted whether or not this realm publishes a level (or a
    # map): an omitted key cannot tell "this realm ships no level" apart from
    # "this ack came from a hermes that has no level family", and the
    # launcher's skew rule needs both — the same argument the two projections
    # below already carry.
    rows["level_sync"] = _published_row(resolved.level_hashes, resolved.level_refused, published=published)
    rows["map_sync"] = _published_row(resolved.map_hashes, resolved.map_refused, published=published)
    if resolved.instance_projection is not None:
        rows["persona_instance_projection"] = _persona_instance_row(
            resolved.instance_projection, resolved.instance_rows_unreadable
        )
    if resolved.flow_graph_projection is not None:
        rows["flow_graph_projection"] = _flow_graph_row(resolved.flow_graph_projection)
    return rows


def _published_row(hashes: Any, refused: Any, *, published: bool) -> dict[str, Any]:
    row: dict[str, Any] = {"published": sorted(hashes or {})} if published else {}
    row["refused"] = list(refused or [])
    return row


# ── the per-family baseline records, and the table that runs them ─────────────
#
# Every family records what it just shipped as its never-synced baseline, so my
# own publish never comes back as a pull conflict (a HOLD on bytes I shipped).
# Each record is best-effort: a baseline is a receipt and never fails a publish,
# and ``_record_publish_baselines`` is the one place that says so.


def _record_board_baseline(realm: Realm, resolved: _ResolvedPublish) -> None:
    # Board ids are resolved from the local boards that contributed artifacts
    # (not the tokenized subtree dir names).
    from ..board_sync import update_board_baseline_after_sync

    published_board_ids = sorted({
        artifact.source.parent.parent.name if artifact.kind == SyncFamily.BOARD_CARD else artifact.source.parent.name
        for artifact in resolved.artifacts
        if artifact.kind in (SyncFamily.BOARD, SyncFamily.BOARD_CARD)
    })
    if published_board_ids:
        update_board_baseline_after_sync(realm.id, published_board_ids)


def _record_office_baseline(realm: Realm, resolved: _ResolvedPublish) -> dict[str, Any] | None:
    # Per workspace (tokens resolved from the local office dirs that contributed
    # artifacts). Its receipt is the only one the publish envelope carries.
    from ..office_sync import update_office_baseline_after_sync

    published_office_workspaces = sorted({
        artifact.source.parent.parent.name if artifact.kind == SyncFamily.OFFICE_ACTOR else artifact.source.parent.name
        for artifact in resolved.artifacts
        if artifact.kind in (SyncFamily.OFFICE, SyncFamily.OFFICE_ACTOR)
    })
    if not published_office_workspaces:
        return None
    return update_office_baseline_after_sync(realm.id, published_office_workspaces).as_dict()


def _record_persona_config_baseline(realm: Realm, resolved: _ResolvedPublish) -> None:
    from ..persona_config_sync import update_persona_config_baseline_after_publish

    update_persona_config_baseline_after_publish(realm.id, resolved.projection)


def _record_profile_files_baseline(realm: Realm, resolved: _ResolvedPublish) -> None:
    # MEMORY.md / core context / persona prompts: my own publish never comes back
    # as a pull hold.
    from ..profile_artifact_sync import update_profile_artifact_baseline_after_publish

    update_profile_artifact_baseline_after_publish(realm.id, _published_profile_file_hashes(resolved.artifacts))


def _record_persona_instance_baseline(realm: Realm, resolved: _ResolvedPublish) -> None:
    # Without it a publisher who then pulls sees every row they just shipped as
    # locally-edited-and-remotely-changed, i.e. a HOLD on their own publish.
    from ..persona_instance_sync import update_persona_instance_baseline_after_publish

    if resolved.instance_projection is not None:
        update_persona_instance_baseline_after_publish(realm.id, resolved.instance_projection)


def _record_flow_graph_baseline(realm: Realm, resolved: _ResolvedPublish) -> None:
    # It matters more for the CANVAS: a held record is an absence; a held DRAWING
    # is a conflict sidecar over content nobody disagreed about.
    from ..flow_graph_sync import update_flow_graph_baseline_after_publish

    if resolved.flow_graph_projection is not None:
        update_flow_graph_baseline_after_publish(realm.id, resolved.flow_graph_projection)


def _record_level_baseline(realm: Realm, resolved: _ResolvedPublish) -> None:
    # A level merges at WHOLE-DOCUMENT granularity, so a two-sided divergence is
    # a HOLD with a conflict sidecar — without this the publisher's very next
    # pull hands them a held environment over the bytes they just shipped.
    from ..level_sync import update_level_baseline_after_publish

    if resolved.level_hashes:
        update_level_baseline_after_publish(realm.id, dict(resolved.level_hashes))


def _record_map_baseline(realm: Realm, resolved: _ResolvedPublish) -> None:
    # The level family's discipline for the level family's reason: a held
    # catalogue over the bytes the publisher just shipped.
    from ..map_sync import update_map_baseline_after_publish

    if resolved.map_hashes:
        update_map_baseline_after_publish(realm.id, dict(resolved.map_hashes))


#: Every family whose baseline a publish records, in the order they are
#: recorded. ``_record_publish_baselines`` iterates this and nothing else; the
#: skill family is the one exception, and ``publish_realm_sync`` says why.
BASELINE_FAMILIES: Final[tuple[tuple[SyncFamily, Callable[[Realm, _ResolvedPublish], Any]], ...]] = (
    (SyncFamily.BOARD, _record_board_baseline),
    (SyncFamily.OFFICE, _record_office_baseline),
    (SyncFamily.PERSONA_CONFIG, _record_persona_config_baseline),
    (SyncFamily.PROFILE_FILE, _record_profile_files_baseline),
    (SyncFamily.PERSONA_INSTANCE, _record_persona_instance_baseline),
    (SyncFamily.FLOW_GRAPH, _record_flow_graph_baseline),
    (SyncFamily.LEVEL, _record_level_baseline),
    (SyncFamily.MAP, _record_map_baseline),
)


def _record_publish_baselines(realm: Realm, resolved: _ResolvedPublish) -> dict[SyncFamily, Any]:
    """Run every family's baseline record: ``{family: receipt}``, ``None`` for a
    family whose record raised."""

    receipts: dict[SyncFamily, Any] = {}
    for family, record in BASELINE_FAMILIES:
        try:
            receipts[family] = record(realm, resolved)
        except Exception:  # noqa: BLE001 — baseline is best-effort; never fail publish
            receipts[family] = None
    return receipts


def _notify_publish(realm: Realm, *, repo: Path, artifacts: list[RealmSyncArtifact], credential: "RealmSyncCredential | None") -> list[dict[str, Any]]:
    """Best-effort counts-only publish notification (Stage 43 C4).

    A notify failure is downgraded to a ``warnings[]`` entry on the success
    envelope — the publish itself already landed and must not be failed.
    """
    if credential is None:
        return []
    commit = _git(repo, "rev-parse", "HEAD", check=False).strip()
    counts: dict[str, int] = {}
    for artifact in artifacts:
        counts[artifact.kind] = counts.get(artifact.kind, 0) + 1
    from ..realm_membership import notify_realm_published

    try:
        notify_realm_published(credential, realm.id, commit=commit, artifact_counts=counts)
    except RealmSyncError as exc:
        return [
            {
                "code": "sync_notify_failed",
                "message": "Publish succeeded but the backend publish notification failed; members will not receive a realtime update signal.",
                "retryable": bool(exc.retryable),
            }
        ]
    return []


def _record_skill_publish_baseline(realm: Realm, *, subtree: Path) -> None:
    """After a successful publish: record what shipped, then refresh the mirror.

    TWO steps, in this order, and the order is the argument:

    1. ``update_skill_baseline_after_publish`` over every package this realm
       publishes (``publishable_skill_packages`` — the publish's own iteration),
       hashed from the canonical package, which is what was published. Entries for
       packages no longer published are dropped by that function, so a de-selected
       or deleted slug stops being accounted.
    2. re-mirror the inbox from the subtree. The subtree is the realm's state now
       that the push has succeeded, and the inbox is what every skill decision
       reads. Without this step the inbox keeps the pre-publish copy and the hold
       the operator just published away survives until their next pull.

    Both are best-effort, like every sibling family's baseline write: a receipt
    never fails a publish, and the mirror is a cache the next pull rebuilds.
    Tombstoned packages are dropped from the mirror by
    ``_mirror_realm_skill_inbox`` itself, through the same ledger predicate the
    pull passes it, so this can never resurrect a deleted slug into the inbox.
    """

    from ..skill_promotion import realm_inbox_dir, skill_package_sync_hash
    from ..skill_sync import update_skill_baseline_after_publish

    try:
        update_skill_baseline_after_publish(
            realm.id,
            {
                slug: skill_package_sync_hash(package_dir)
                for slug, package_dir in publishable_skill_packages(realm)
            },
        )
    except Exception:  # noqa: BLE001 — baseline is best-effort; never fail publish
        logger.exception("skill baseline write failed after publish for realm %s", realm.id)
    try:
        _mirror_realm_skill_inbox(
            subtree / "skills",
            realm_inbox_dir(realm.id),
            tombstoned=lambda slug: skill_tombstoned(realm, slug) is not None,
        )
    except Exception:  # noqa: BLE001 — the mirror is a cache the next pull rebuilds
        logger.exception("skill inbox re-mirror failed after publish for realm %s", realm.id)


def _published_artifacts_differ(subtree: Path, desired: dict[str, bytes]) -> bool:
    """True when the canonical published bytes differ from what is already in the
    realm subtree, ignoring manifest.json (its ``generated_at`` is volatile).

    ``desired`` is canonical (LF); the on-disk bytes are compared RAW, so a legacy
    CRLF subtree triggers a one-time LF migration on the next publish while an
    already-canonical subtree is a true no-op (no rewrite, no commit)."""
    if not subtree.exists():
        return bool(desired)
    existing: dict[str, bytes] = {}
    for path in subtree.rglob("*"):
        if path.is_file() and path.name != "manifest.json":
            existing[path.relative_to(subtree).as_posix()] = path.read_bytes()
    return existing != desired
