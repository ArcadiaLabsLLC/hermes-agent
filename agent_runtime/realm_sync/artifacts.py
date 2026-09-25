"""What a realm publishes: ONE resolution pass over every family.

``_resolve_artifacts_with_projection`` is the single authority for "what does this
realm publish"; the skill package walk, the realm/workspace records and the agent
selection read it or feed it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.skill_utils import EXCLUDED_SKILL_DIRS, SKILL_SUPPORT_DIRS
from agent_runtime.profile_home import get_shared_skills_dir

from .. import paths
from ..config import ensure_persisted_personas, load_agent_runtime_config
from ..models import Realm, Workspace
from ..store import RealmStore, WorkspaceStore, skill_tombstoned
from .models import RealmSyncArtifact, RealmSyncError
from .families import _is_hard_excluded_path
from .publish_scans import (
    _board_publish_scan,
    _level_publish_scan,
    _map_publish_scan,
    _office_publish_scan,
)
from .persona_artifacts import (
    _bound_profile_name,
    _flow_graph_artifact,
    _office_wanted_persona_ids,
    _persona_artifacts,
    _persona_config_artifact,
    _persona_instance_artifact,
    _raw_active_config,
)

__layer__ = "stores"
__all__ = [
    "_ResolvedPublish",
    "_append_skill_package_artifacts",
    "_dedupe_artifacts",
    "_distinct_skill_package_count",
    "_flow_graph_projection",
    "_iter_publishable_skill_packages",
    "_persona_instance_projection",
    "_required_realm_persona_ids",
    "_resolve_artifacts_with_projection",
    "_skill_artifacts",
    "_skill_slug_selected",
    "_workspace_realm_artifacts",
    "_workspaces_for_realm",
    "publishable_skill_packages",
    "realm_agent_selection_state",
    "resolve_realm_sync_artifacts",
    "sync_artifacts_for_workspace_agent",
]


@dataclass(frozen=True, slots=True)
class _ResolvedPublish:
    """Everything ONE resolution pass of "what does this realm publish" yields.

    The publish lane needs the projection's ACCOUNTING (which keys the allowlist
    dropped, which definitions came purely from a store record, which config keys
    the record shadowed, which wanted personas had no definition at all)
    alongside the artifacts. Resolving them in one pass keeps a single authority
    for "what does this realm publish" — a second independent computation could
    drift from the bytes actually written.

    - ``profile_files_withheld`` — the same discipline for the profile-FILE
      family: a prompt that could not travel is a typed row, never a silent
      omission.
    - ``bound_profiles`` — the profile HOMES this publish resolved persona files
      out of, taken from ``resolve_persona_profile`` (the binding authority
      ``_persona_artifacts`` itself uses). ``profiles_withheld`` used to be
      re-derived by reading ``hermes_profile`` back out of the projected bodies,
      which went blind for the same reason the projection did: a partial body
      reported the wrong profile set and ``base_seed_guarded: false``. A derived
      artifact is not an authority.
    """

    artifacts: list[RealmSyncArtifact]
    projection: Any
    profile_files_withheld: list[dict[str, str]]
    bound_profiles: list[str]
    #: Office workspaces this pass would not publish because their actor
    #: directory did not fully read. Same discipline as ``profile_files_withheld``
    #: one field up: a family that could not travel is a typed row, never a
    #: silent omission — and here silence would have published a partial office
    #: that every peer reads as desk removals.
    office_refused: list[dict[str, Any]] = ()  # type: ignore[assignment]
    #: The board family's twin of the field above, same discipline.
    board_refused: list[dict[str, Any]] = ()  # type: ignore[assignment]
    #: The persona-INSTANCE projection resolved by the same pass — its bodies and
    #: its accounting (dropped keys, canonical rows skipped, records refused,
    #: wanted ids with no row). ``None`` only in the degenerate case where the
    #: instance store itself could not be read; an EMPTY projection is a
    #: different fact and says so.
    instance_projection: Any = None
    #: Instance rows on this machine that would not decode during the publish
    #: walk. Carried rather than dropped for the ``ActorScan.unreadable``
    #: reason — a shortened answer must state its own shortfall. It is NOT a
    #: delete here: a peer that misses an instance from the projection classifies
    #: it ``upstream_absent`` (plan §3.3), which is explicitly held, not archived.
    instance_rows_unreadable: int = 0
    #: The CANVAS projection resolved by the same pass — the operator's drawing
    #: for exactly the desks above. A realm that never drew one yields an EMPTY
    #: projection and the artifact is then not appended at all, so a graph-less
    #: realm publishes byte-identically to before this family existed.
    flow_graph_projection: Any = None
    #: The workspace LEVEL family's published content hashes, keyed by workspace
    #: token. Carried out of the SAME pass that minted the artifacts, and spent
    #: by the publish to record the baseline — never re-walked, because a second
    #: walk of ``store/levels/`` could disagree with the bytes actually written
    #: and the disagreement would show up as a HOLD on the publisher's own
    #: environment.
    level_hashes: dict[str, str] = ()  # type: ignore[assignment]
    #: Levels this pass would not publish because the document would not read.
    #: Same discipline as ``office_refused``: a family that could not travel is a
    #: typed row, never a silent omission — and here silence would let a peer
    #: read the absence as "the realm removed this level".
    level_refused: list[dict[str, Any]] = ()  # type: ignore[assignment]
    #: The MAP CATALOGUE family's published content hashes, keyed by map token.
    #: Out of the SAME pass that minted the artifacts, for ``level_hashes``'s
    #: reason — a second walk of ``store/maps/`` could disagree with the bytes
    #: actually written, and the disagreement surfaces as a HOLD on the
    #: publisher's own catalogue.
    map_hashes: dict[str, str] = ()  # type: ignore[assignment]
    #: Maps this pass would not publish because the document would not read.
    #: A typed row, never a silent omission: silence would let a peer read the
    #: absence as "the realm removed this map", which is the ``unnamed`` caption
    #: this family exists to stop.
    map_refused: list[dict[str, Any]] = ()  # type: ignore[assignment]


def resolve_realm_sync_artifacts(realm_id: str) -> list[RealmSyncArtifact]:
    return _resolve_artifacts_with_projection(realm_id).artifacts


def _resolve_artifacts_with_projection(realm_id: str) -> _ResolvedPublish:
    realm = RealmStore().get(realm_id)
    workspaces = _workspaces_for_realm(realm)
    cfg = load_agent_runtime_config()
    personas = {persona.id: persona for persona in ensure_persisted_personas(cfg)}
    artifacts: list[RealmSyncArtifact] = []
    artifacts.extend(_skill_artifacts(realm))
    artifacts.extend(_workspace_realm_artifacts(realm, workspaces))
    board_scan = _board_publish_scan(workspaces)
    artifacts.extend(board_scan.artifacts)
    # ONE office pass: the artifacts, the persona ids those placements require,
    # and the workspaces that would not publish at all, resolved together so the
    # three cannot disagree about which offices are in this publish.
    office_scan = _office_publish_scan(workspaces)
    artifacts.extend(office_scan.artifacts)
    # The workspace LEVEL family (launcher R15). Independent of the office by
    # ruling rather than by convenience: R7 says a level is the ENVIRONMENT and
    # the office's actors are the CONTENTS placed on it, stored separately, and
    # "the two documents never merge". So it is its own scan over its own store
    # directory, and a workspace whose office refuses still publishes its level.
    level_scan = _level_publish_scan(workspaces)
    artifacts.extend(level_scan.artifacts)
    # The MAP CATALOGUE family. Takes NO workspace argument, and that is the one
    # structural difference from every scan above it: a level is addressed BY a
    # workspace and a workspace belongs to a realm, but a map id belongs to
    # nothing smaller than the install, so there is no id set to filter against.
    # A realm carries the whole catalogue — see ``map_sync``'s module docstring
    # for why that trade is the cheaper half.
    map_scan = _map_publish_scan()
    artifacts.extend(map_scan.artifacts)
    # Personas referenced by synced office placements travel with the office
    # (plan §5): an office-only persona must be materializable on pull. The
    # wanted set was workspace.agent_ids only, which would sync a placement
    # referencing a persona the member cannot resolve.
    required_persona_ids = _required_realm_persona_ids(
        workspaces, office_persona_ids=office_scan.persona_ids
    )
    selected_persona_ids = (
        list(realm.agent_selection or [])
        if getattr(realm, "agent_publish_mode", "workspace") == "selected"
        else []
    )
    wanted_persona_ids = list(
        dict.fromkeys([*required_persona_ids, *selected_persona_ids])
    )
    published_persona_ids: list[str] = []
    profile_files_withheld: list[dict[str, str]] = []
    bound_profiles: set[str] = set()
    for persona_id in wanted_persona_ids:
        persona = personas.get(persona_id)
        if persona is None:
            continue
        published_persona_ids.append(persona_id)
        bound_profiles.add(_bound_profile_name(persona))
        persona_artifacts, withheld = _persona_artifacts(persona)
        artifacts.extend(persona_artifacts)
        profile_files_withheld.extend(withheld)
    # ONE synthesized, portable persona-definition document for the whole realm,
    # pruned to exactly the personas above. Replaces the per-profile raw
    # ``config.yaml`` artifact that used to leak the base seed and every
    # machine-shaped MCP/env/path value on it.
    from ..persona_config_sync import project_persona_definitions

    projection = project_persona_definitions(
        published_persona_ids,
        raw_config=_raw_active_config(),
        records=personas,
    )
    if projection.personas:
        artifacts.append(_persona_config_artifact(projection))
    # The persona-INSTANCE projection: the agents behind the desks this publish
    # is already shipping. Pruned to exactly ``office_scan.instance_ids`` — the
    # ids resolved in the office walk above, never a second enumeration — so a
    # workspace the office scan refused contributes no instance either.
    instance_projection, instance_rows_unreadable = _persona_instance_projection(
        office_scan.instance_ids
    )
    if instance_projection.instances:
        artifacts.append(_persona_instance_artifact(instance_projection))
    # The CANVAS projection: the operator's drawing for those same desks, on the
    # SAME id list for the same reason — a canvas is addressed to an owner
    # instance, so a desk this publish does not ship has no canvas to ship
    # either.
    flow_graph_projection = _flow_graph_projection(office_scan.instance_ids)
    if flow_graph_projection.graphs:
        artifacts.append(_flow_graph_artifact(flow_graph_projection))
    return _ResolvedPublish(
        artifacts=_dedupe_artifacts(artifacts),
        projection=projection,
        profile_files_withheld=profile_files_withheld,
        bound_profiles=sorted(bound_profiles),
        office_refused=office_scan.refused,
        board_refused=board_scan.refused,
        instance_projection=instance_projection,
        instance_rows_unreadable=instance_rows_unreadable,
        flow_graph_projection=flow_graph_projection,
        level_hashes=level_scan.hashes,
        level_refused=level_scan.refused,
        map_hashes=map_scan.hashes,
        map_refused=map_scan.refused,
    )


def _flow_graph_projection(instance_ids: list[str]):
    """The canvas projection for the desks this publish already ships.

    One store read per owner (``FlowGraphStore.get``) rather than a walk of the
    graph directory, and that asymmetry with ``_persona_instance_projection``
    above is deliberate: the instance store's ``scan_all`` reports its own
    unreadable count because a missing instance is a fact about a desk that IS
    being published, whereas the graph directory legitimately holds canvases for
    owners no realm places (archived desks' drawings are kept, never deleted).
    Walking it would make every one of those look like a shortfall.

    A store that cannot be constructed at all yields an empty projection: the
    canvas is additive to a publish, so its absence must never fail one.
    """

    from ..flow_graph import FlowGraphStore
    from ..flow_graph_sync import graph_id_for_owner, project_flow_graphs

    wanted = [str(item) for item in (instance_ids or [])]
    try:
        store = FlowGraphStore()
        docs = {owner: store.get(graph_id_for_owner(owner)) for owner in wanted}
    except Exception:  # noqa: BLE001 — accounted as "no canvas", never a failed publish
        docs = {}
    return project_flow_graphs(wanted, docs=docs)


def _persona_instance_projection(instance_ids: list[str]):
    """``(projection, unreadable_row_count)`` for the wanted instance ids.

    The store's ``scan_all`` is THE reader — not a second glob of
    ``persona_instances/`` — and its ``unreadable`` count is spent rather than
    dropped. Spending it here is cheap because a short answer in THIS family
    costs an absence, not a deletion: an instance missing from the published
    projection while its desk is still present is ``upstream_absent`` on every
    peer (plan §3.3, §5.2), which is held and accounted. That is the whole
    reason this arm does not have to refuse the way the office scan does.
    """

    from ..persona_assignments import PersonaInstanceStore
    from ..persona_instance_sync import project_persona_instances

    wanted = [str(item) for item in (instance_ids or [])]
    try:
        scan = PersonaInstanceStore().scan_all()
        records = {instance.id: instance for instance in scan.instances}
        unreadable = scan.unreadable
    except Exception:  # noqa: BLE001 — accounted below, never a failed publish
        records, unreadable = {}, 0
    return project_persona_instances(wanted, records=records), unreadable


def _workspaces_for_realm(realm: Realm) -> list[Workspace]:
    workspace_store = WorkspaceStore()
    workspace_ids = set(realm.workspace_ids or [])
    for workspace in workspace_store.list_all(include_archived=True):
        if workspace.realm_id == realm.id:
            workspace_ids.add(workspace.id)
    # Tombstoned workspaces never publish (defense-in-depth: the pull already
    # deletes local copies, but a publish racing ahead of its pull must not
    # resurrect a deleted workspace into the realm subtree).
    workspace_ids -= set(realm.deleted_workspace_ids or [])
    return [
        workspace_store.get(workspace_id)
        for workspace_id in sorted(workspace_ids)
        if paths.workspace_path(workspace_id).exists()
    ]


def _required_realm_persona_ids(
    workspaces: list[Workspace], *, office_persona_ids: list[str] | None = None
) -> list[str]:
    """Persona definitions required by synchronized references.

    These rows are pinned regardless of the explicit Realm selection: a
    pulled workspace roster or Office placement must never reference a persona
    definition the same publish deliberately omitted.

    ``office_persona_ids`` is passed by the publish resolver so this answer and
    the office ARTIFACTS come from the same scan; recomputing it here would let
    a workspace refused for unreadable actors still pin its personas.
    """
    workspace_ids = [
        persona_id
        for workspace in workspaces
        for persona_id in (workspace.agent_ids or [])
    ]
    office_ids = (
        list(office_persona_ids)
        if office_persona_ids is not None
        else _office_wanted_persona_ids(workspaces)
    )
    return list(dict.fromkeys([*workspace_ids, *office_ids]))


def realm_agent_selection_state(realm_id: str) -> dict[str, Any]:
    """Return the local catalog and effective Realm persona selection.

    Pure with respect to Realm selection: unknown ids are preserved and
    reported, while required workspace/Office references remain pinned in the
    effective published set.
    """
    realm = RealmStore().get(realm_id)
    workspaces = _workspaces_for_realm(realm)
    catalog_personas = ensure_persisted_personas(load_agent_runtime_config())
    catalog = sorted({persona.id for persona in catalog_personas})
    required = sorted(set(_required_realm_persona_ids(workspaces)))
    selection = sorted(set(getattr(realm, "agent_selection", None) or []))
    mode = getattr(realm, "agent_publish_mode", "workspace") or "workspace"
    effective = set(required)
    if mode == "selected":
        effective.update(selection)
    published = sorted(effective & set(catalog))
    missing = sorted(effective - set(catalog))
    return {
        "mode": mode,
        "selection": selection,
        "catalog": catalog,
        "required": required,
        "published": published,
        "missing": missing,
    }


def sync_artifacts_for_workspace_agent(workspace_id: str, persona_id: str) -> list[dict[str, str]]:
    workspace = WorkspaceStore().get(workspace_id)
    if not workspace.realm_id:
        return []
    artifacts = resolve_realm_sync_artifacts(workspace.realm_id)
    needle = f"/{paths.safe_path_token(persona_id)}/"
    # Explicit attribution first (the profile-file family publishes at a
    # destination-shaped path where the persona token no longer appears), path
    # substring second (skills and everything else that still encodes it).
    return [
        artifact.row()
        for artifact in artifacts
        if artifact.persona_id == persona_id or needle in f"/{artifact.relative_path}"
    ]


def _skill_artifacts(realm: Realm) -> list[RealmSyncArtifact]:
    # Publish the shared canonical skills root (see get_shared_skills_dir) —
    # the one physical dir every persona references. Walk each skill package
    # WHOLE (not just SKILL.md) so multi-file skills — references/, scripts/,
    # assets/, templates/ — travel intact to every realm member. Sub-path
    # filenames are kept verbatim (rglob cannot emit ``..``) so files like
    # ``__init__.py`` are not mangled. Junk/VCS/cache/dot components are pruned;
    # the shared secret/state validation still runs over the result
    # (_assert_no_secret_artifacts).
    #
    # Package shapes (C5): a top-level dir WITH a SKILL.md publishes as a bare
    # slug; a top-level dir WITHOUT one is a category whose immediate child dirs
    # with a SKILL.md publish as ``<parent>/<child>`` (one level only). A
    # categorized skill such as ``software-development/hermes-agent`` — selected
    # BY PATH by personas — otherwise never reaches a realm.
    #
    # Per-realm selection: mode "all" (default) publishes every catalog package;
    # mode "selected" publishes a package whose slug — or, for a categorized
    # package, the bare child name — is in realm.skill_selection. Because publish
    # rebuilds the realm subtree from scratch, filtering here naturally prunes
    # deselected skills on the next publish. Bare slugs line up with what the
    # Launcher picker offers; categorized selection by bare child name works
    # today (the picker doesn't yet offer categorized slugs — documented
    # follow-up), and the categorized id itself is honored too.
    #
    # Deleted skills never publish, whatever the selection says (the
    # ``workspace_ids -= deleted_workspace_ids`` idiom in
    # ``_workspaces_for_realm``). Normally the pull already archived the local
    # canonical copy, so this filter has nothing to do — it is the
    # defense-in-depth half for a copy re-materialized out of band (a stray
    # ``promote --from-path``, a manual copy) and for a publish racing ahead of
    # its pull. Together with the existing chain — a stale member's publish is
    # refused ``sync_behind`` → they pull → the pull hands them the ledger in the
    # realm JSON → ``_apply_skill_tombstones`` archives their copy → their
    # retried publish neither contains the skill nor could include it — this is
    # why no server-side hook is needed: every writer is a hermes running this
    # code, and the git host can only gate WHO writes, never WHAT is written.
    root = get_shared_skills_dir()
    artifacts: list[RealmSyncArtifact] = []
    for slug, package_dir in publishable_skill_packages(realm):
        _append_skill_package_artifacts(artifacts, root, slug, package_dir)
    return artifacts


def publishable_skill_packages(realm: Realm) -> list[tuple[str, Path]]:
    """``(slug, canonical package dir)`` for every package THIS realm publishes.

    The canonical-root walk plus the two filters — publish mode / selection, and
    the realm's skill-delete ledger — as ONE function, because three lanes need
    the identical answer and three copies of a filter chain are free to disagree:

    * ``_skill_artifacts`` (the publish itself),
    * ``_record_skill_publish_baseline`` (what the baseline records after a push),
    * ``_skill_store_drift_items`` (what counts as unpublished local drift).

    It was inline in the publish walk until 2026-09-12, when the other two
    arrived. A drift row for a package the publish would not ship offers the
    operator a Publish that changes nothing, and a baseline entry for one offers a
    Revert that reinstalls it — so "the same iteration as the publish" is a
    correctness requirement here, not a style preference.
    """

    root = get_shared_skills_dir()
    if not root.is_dir():
        return []
    selected_only = realm.skill_publish_mode == "selected"
    selection = set(realm.skill_selection or [])
    return [
        (slug, package_dir)
        for slug, package_dir in _iter_publishable_skill_packages(root)
        if not (selected_only and not _skill_slug_selected(slug, selection))
        and skill_tombstoned(realm, slug) is None
    ]


def _iter_publishable_skill_packages(root: Path):
    """Yield ``(slug, package_dir)`` for every publishable canonical skill package.

    A top-level dir with a ``SKILL.md`` is a bare package (slug = its name). A
    top-level dir WITHOUT a ``SKILL.md`` is a category: each immediate child dir
    with a ``SKILL.md`` publishes as ``<parent>/<child>`` (one level only —
    multi-level nesting is out of scope). Dot-prefixed dirs (the
    resolver-invisible ``.realm_inbox`` / ``.provenance`` / ``.archive`` live
    here), excluded housekeeping dirs, and — under a category — support dirs are
    skipped, so quarantine and provenance are publish-invisible for free.
    """

    for top in sorted(p for p in root.iterdir() if p.is_dir()):
        name = top.name
        if name.startswith(".") or name in EXCLUDED_SKILL_DIRS:
            continue
        if (top / "SKILL.md").is_file():
            yield name, top
            continue
        for child in sorted(p for p in top.iterdir() if p.is_dir()):
            cname = child.name
            if (
                cname.startswith(".")
                or cname in EXCLUDED_SKILL_DIRS
                or cname in SKILL_SUPPORT_DIRS
            ):
                continue
            if (child / "SKILL.md").is_file():
                yield f"{name}/{cname}", child


def _skill_slug_selected(slug: str, selection: set[str]) -> bool:
    """``selected``-mode match: the package slug itself, or — for a categorized
    ``<parent>/<child>`` slug — the bare child name (C5)."""

    if slug in selection:
        return True
    if "/" in slug:
        return slug.split("/", 1)[1] in selection
    return False


def _append_skill_package_artifacts(
    artifacts: list[RealmSyncArtifact], root: Path, slug: str, package_dir: Path
) -> None:
    from agent_runtime.skill_resolution import resolve_skill

    resolution = resolve_skill(slug)
    selected = resolution.candidate
    if (
        resolution.status != "resolved"
        or selected is None
        or selected.source_kind != "shared_core"
    ):
        raise RealmSyncError(
            "skill_authority_conflict",
            f"Skill cannot publish until shared authority resolves uniquely: {slug}",
            safe_details={
                "skill": slug,
                "resolution_status": resolution.status,
                "candidate_count": len(resolution.candidates),
            },
        )
    skill_dir = selected.skill_dir or selected.skill_md.parent
    safe_parts = [paths.safe_path_token(part) for part in slug.split("/")]
    prefix = "/".join(safe_parts)
    dest_root = root.joinpath(*safe_parts)
    for source in sorted(skill_dir.rglob("*")):
        if not source.is_file():
            continue
        rel_parts = source.relative_to(skill_dir).parts
        if any(
            part.startswith(".") or part in EXCLUDED_SKILL_DIRS for part in rel_parts
        ):
            continue
        rel_within = "/".join(rel_parts)
        artifacts.append(
            RealmSyncArtifact(
                kind="skill",
                source=source,
                relative_path=f"skills/{prefix}/{rel_within}",
                destination=dest_root / Path(*rel_parts),
            )
        )


def _workspace_realm_artifacts(realm: Realm, workspaces: list[Workspace]) -> list[RealmSyncArtifact]:
    artifacts = [
        RealmSyncArtifact(
            kind="realm",
            source=paths.realm_path(realm.id),
            relative_path=f"store/realms/{paths.safe_path_token(realm.id)}.json",
            destination=paths.realm_path(realm.id),
        )
    ]
    for workspace in workspaces:
        artifacts.append(
            RealmSyncArtifact(
                kind="workspace",
                source=paths.workspace_path(workspace.id),
                relative_path=f"store/workspaces/{paths.safe_path_token(workspace.id)}.json",
                destination=paths.workspace_path(workspace.id),
            )
        )
    return [item for item in artifacts if item.source.exists()]


def _distinct_skill_package_count(artifacts: list[RealmSyncArtifact]) -> int:
    """Number of distinct skill *packages* (top-level skill dir names) among
    resolved artifacts — not the file count. A multi-file skill counts once."""
    packages: set[str] = set()
    for artifact in artifacts:
        if artifact.kind != "skill":
            continue
        parts = Path(artifact.relative_path).parts
        if len(parts) >= 2:
            packages.add(parts[1])
    return len(packages)


def _dedupe_artifacts(artifacts: list[RealmSyncArtifact]) -> list[RealmSyncArtifact]:
    deduped: dict[str, RealmSyncArtifact] = {}
    for artifact in artifacts:
        # A synthesized artifact has no file to exist — its bytes ARE the
        # artifact. Only file-backed artifacts are dropped when their source
        # vanished between resolution and publish.
        if artifact.content is None and not artifact.source.exists():
            continue
        rel = artifact.relative_path.replace("\\", "/")
        if _is_hard_excluded_path(rel):
            continue
        deduped[rel] = artifact
    return [deduped[key] for key in sorted(deduped)]
