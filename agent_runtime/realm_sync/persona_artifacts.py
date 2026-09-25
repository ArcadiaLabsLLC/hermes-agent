"""The persona-shaped artifacts: profile files, the synthesized projections and their guards.

Per-persona profile FILES, the three synthesized documents (persona definitions,
persona instances, canvases), their accounting rows, the base-seed and portability
guards, and the pull side's subtree-to-artifact walk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hermes_constants import get_config_path, get_hermes_home

from .. import paths
from ..models import AgentPersona, Workspace
from ..profile_context import active_profile_name, resolve_persona_profile
from .models import BASE_PROFILE_NAME, RealmSyncArtifact, RealmSyncError
from .families import _destination_for_sync_path, _kind_for_sync_path
from .git import _redact_text
from .publish_scans import _office_publish_scan

__layer__ = "stores"
__all__ = [
    "_artifacts_from_subtree",
    "_assert_no_raw_profile_config",
    "_assert_portable_artifacts",
    "_bound_profile_name",
    "_flow_graph_artifact",
    "_flow_graph_row",
    "_is_raw_profile_config_path",
    "_office_wanted_persona_ids",
    "_persona_artifacts",
    "_persona_config_artifact",
    "_persona_instance_artifact",
    "_persona_instance_row",
    "_persona_projection_row",
    "_profile_files_row",
    "_profile_relative_destination",
    "_profile_relative_file",
    "_published_profile_file_hashes",
    "_raw_active_config",
]


def _office_wanted_persona_ids(workspaces: list[Workspace]) -> list[str]:
    """Persona ids referenced by office placements in this realm's workspaces
    (plan §5's one-line union — office-only personas travel with the office).

    Thin view over :func:`_office_publish_scan`, so a workspace whose office is
    refused never contributes a persona id: the placement that would have needed
    it is not travelling either."""

    return _office_publish_scan(workspaces).persona_ids


def _published_profile_file_hashes(artifacts: list[RealmSyncArtifact]) -> dict[str, str]:
    """``{entity key: content hash}`` for the profile FILES this publish wrote.

    Feeds the publish-side baseline update so a member who publishes then pulls
    sees local == baseline (no self-inflicted hold)."""

    from ..profile_artifact_sync import (
        PROFILE_FILES_ROOT,
        classify_destination,
        content_hash,
        entity_key,
    )

    prefix = f"{PROFILE_FILES_ROOT}/"
    hashes: dict[str, str] = {}
    for artifact in artifacts:
        rel = artifact.relative_path.replace("\\", "/")
        if not rel.startswith(prefix):
            continue
        tail = rel[len(prefix):].split("/", 1)
        if len(tail) != 2 or classify_destination(tail[1]) is None:
            continue
        try:
            hashes[entity_key(tail[0], tail[1])] = content_hash(artifact.read_bytes())
        except OSError:
            continue
    return hashes


def _profile_files_row(
    artifacts: list[RealmSyncArtifact], withheld: list[dict[str, str]]
) -> dict[str, Any]:
    """Typed publish accounting for the profile-FILE family.

    ``published`` names every destination that travels (keyed exactly as the pull
    side reconciles it, so a publish row and a pull hold are the same string);
    ``withheld`` names every file that deliberately did not — today only
    repository-bundled prompts, which already ship with every member's hermes.
    """

    from ..profile_artifact_sync import PROFILE_FILES_ROOT

    prefix = f"{PROFILE_FILES_ROOT}/"
    published = sorted(
        {
            artifact.relative_path.replace("\\", "/")[len(prefix):].replace("/", ":", 1)
            for artifact in artifacts
            if artifact.relative_path.replace("\\", "/").startswith(prefix)
        }
    )
    return {"published": published, "withheld": list(withheld)}


def _persona_artifacts(persona: AgentPersona) -> tuple[list[RealmSyncArtifact], list[dict[str, str]]]:
    """Per-profile FILES a persona carries: prompts, soul overlay, memory, core
    context. Returns ``(artifacts, withheld rows)``.

    The bound profile home's RAW ``config.yaml`` is deliberately NOT here any
    more. It used to publish as ``profiles/<profile>/config.yaml`` and overwrite
    the member's file wholesale on pull, which (a) clobbered the base fork seed
    whenever a persona bound to ``hermes_profile: base`` (Office plan §5.1 ruled
    that must never happen) and (b) shipped machine-shaped ``mcp_servers``
    commands/env and absolute Windows paths that resolve to nothing on any other
    machine. The persona DEFINITIONS that were the only shareable part of that
    file now travel as one synthesized, allowlisted projection
    (``persona_config_sync.project_persona_definitions``).

    The published PATH changed on 2026-07-25 (see
    ``profile_artifact_sync``): these files now publish at
    ``store/profile_files/<profile>/<profile-relative destination>``, so the
    published tail IS the destination. That (a) makes a prompt round-trip to the
    exact path the persona definition names — the basename-keyed destination did
    not, and left an orphan — and (b) is a path an older hermes does not map, so
    an old member degrades to "no profile files" instead of having their
    accumulated ``MEMORY.md`` overwritten wholesale.

    A prompt that resolves OUTSIDE the bound profile home (a repository-bundled
    role prompt) is deliberately withheld and accounted: it already ships with
    every member's hermes, and publishing it would write a file into the member's
    profile home that no persona definition addresses.
    """

    from ..profile_artifact_sync import (
        CORE_CONTEXT_FILENAMES,
        MEMORY_DESTINATION,
        classify_destination,
        published_relative_path,
    )
    from ..prompt_sources import resolve_persona_system_prompt_path

    binding = resolve_persona_profile(persona)
    profile_home = binding.profile_home or get_hermes_home()
    profile = paths.safe_path_token(binding.hermes_profile or active_profile_name() or "default")
    artifacts: list[RealmSyncArtifact] = []
    withheld: list[dict[str, str]] = []

    def _add(kind: str, source: Path, dest_rel: str) -> None:
        # Publish through the SAME admissibility authority the pull side applies.
        # Without it the two sides can disagree and a file publishes into a realm
        # that every member then refuses — a silent one-way loss. That shipped for
        # a profile-root ``soul.md`` and was caught by the rebind-delta suite on
        # 2026-07-25; this call is why it cannot recur.
        if classify_destination(dest_rel) is None:
            withheld.append(
                {
                    "persona_id": persona.id,
                    "kind": kind,
                    "reason": "destination_not_publishable",
                    "message": f"{dest_rel} is not an admissible profile-file destination; members would refuse it",
                }
            )
            return
        artifacts.append(
            RealmSyncArtifact(
                kind=kind,
                source=source,
                relative_path=published_relative_path(profile, dest_rel),
                destination=source,
                persona_id=persona.id,
            )
        )

    for label, raw in (("system_prompt", persona.system_prompt_path), ("soul_overlay", persona.soul_overlay_path)):
        path = (
            resolve_persona_system_prompt_path(persona)
            if label == "system_prompt"
            else _profile_relative_file(profile_home, raw)
        )
        if path is None or not path.exists():
            continue
        dest_rel = _profile_relative_destination(profile_home, path)
        if dest_rel is None:
            withheld.append(
                {
                    "persona_id": persona.id,
                    "kind": label,
                    "reason": "not_profile_owned",
                    "message": "prompt resolves outside the bound profile home (repository-bundled); it ships with hermes and is not republished",
                }
            )
            continue
        _add(label, path, dest_rel)
    if persona.include_profile_memory:
        memory = profile_home / "memories" / "MEMORY.md"
        if memory.exists():
            _add("profile_memory", memory, MEMORY_DESTINATION)
    if persona.include_core_context_files:
        for name in CORE_CONTEXT_FILENAMES:
            context = profile_home / name
            if context.exists():
                _add("core_context", context, name)
    return artifacts, withheld


def _profile_relative_destination(profile_home: Path, path: Path) -> str | None:
    """``path`` expressed relative to ``profile_home``, or ``None`` when it lives
    outside it. The returned POSIX string is BOTH the published tail and the
    member's destination, which is what makes the round trip exact."""

    try:
        rel = path.resolve().relative_to(profile_home.resolve())
    except (OSError, ValueError):
        return None
    text = rel.as_posix()
    return text or None


def _profile_relative_file(profile_home: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw))
    if path.is_absolute() or ".." in path.parts:
        return None
    return profile_home / path


def _raw_active_config() -> dict[str, Any]:
    """The parsed ``config.yaml`` persona definitions are authored in.

    ``agent_runtime.personas.<id>`` is read by ``load_agent_runtime_config()``
    from ``get_config_path()`` — the ACTIVE profile's config — not from each
    persona's bound profile home. The projection is sourced from the same file
    the runtime resolves definitions out of, so publish and pull are symmetric.
    """

    from ..persona_config_sync import load_raw_config

    return load_raw_config()


def _persona_config_artifact(projection) -> RealmSyncArtifact:
    """The single synthesized ``persona_config`` artifact.

    Published at ``store/personas.yaml``, NOT ``profiles/<name>/config.yaml``:
    an older hermes maps the latter onto ``<profile_home>/config.yaml`` and would
    overwrite a member's real config with this personas-only document. The new
    path is unknown to every older client (``_destination_for_sync_path`` →
    ``None`` → skipped), so an old member degrades to "no persona definitions"
    instead of losing their configuration.
    """

    from ..persona_config_sync import PROJECTION_RELATIVE_PATH

    config = get_config_path()
    return RealmSyncArtifact(
        kind="persona_config",
        source=config,
        relative_path=PROJECTION_RELATIVE_PATH,
        destination=config,
        content=projection.to_bytes(),
    )


def _persona_instance_artifact(projection) -> RealmSyncArtifact:
    """The single synthesized ``persona_instance_config`` artifact.

    Published at ``store/persona_instances.yaml``, a path no older hermes maps
    to anything (``_destination_for_sync_path`` → ``None`` → skipped), so an old
    member degrades to "no instance replication" rather than writing a
    persona-instance document over some unrelated destination. That degrade is
    the whole version-skew contract the launcher's badge demotion keys on.

    ``source``/``destination`` are the local instance directory: this artifact
    is SYNTHESIZED (``content`` is set), so both are provenance only — the
    publish lane reads ``content`` through ``read_bytes`` and never touches
    them.
    """

    from ..persona_instance_sync import PROJECTION_RELATIVE_PATH

    root = paths.persona_instances_dir()
    return RealmSyncArtifact(
        kind="persona_instance_config",
        source=root,
        relative_path=PROJECTION_RELATIVE_PATH,
        destination=root,
        content=projection.to_bytes(),
    )


def _persona_instance_row(projection, unreadable: int) -> dict[str, Any]:
    """Typed publish accounting for the instance family.

    ``rows_unreadable`` is beside the projection's own accounting rather than
    folded into it, because they are different facts: the projection reports
    what it decided about records it COULD read, and this reports how much of
    the store it could not read at all.
    """

    row = projection.as_dict()
    row["rows_unreadable"] = int(unreadable)
    return row


def _flow_graph_artifact(projection) -> RealmSyncArtifact:
    """The single synthesized ``flow_graph_config`` artifact.

    Published at ``store/flow_graphs.yaml``, a path no older hermes maps to
    anything (``_destination_for_sync_path`` → ``None`` → skipped), so an old
    member degrades to "no canvas replication" rather than writing a canvas
    document over some unrelated destination.

    ``source``/``destination`` are the local graph directory: this artifact is
    SYNTHESIZED (``content`` is set), so both are provenance only — the publish
    lane reads ``content`` through ``read_bytes`` and never touches them.
    """

    from ..flow_graph_sync import FLOW_GRAPH_PROJECTION_RELATIVE_PATH

    root = paths.store_root() / "flow_graphs"
    return RealmSyncArtifact(
        kind="flow_graph_config",
        source=root,
        relative_path=FLOW_GRAPH_PROJECTION_RELATIVE_PATH,
        destination=root,
        content=projection.to_bytes(),
    )


def _flow_graph_row(projection) -> dict[str, Any]:
    """Typed publish accounting for the canvas family.

    No ``rows_unreadable`` twin here, and the absence is the point: this family
    reads exactly the owners it was asked for, so there is no "rest of the
    store" it could have failed to read. A canvas it could not decode is a named
    row in ``unreadable``, keyed by the desk that wanted it.
    """

    return projection.as_dict()


def _persona_projection_row(projection, bound_profiles: list[str]) -> dict[str, Any]:
    """Typed publish accounting for the projection — including the explicit
    base-seed guard (Office plan §5.1).

    ``profiles_withheld`` names every profile home whose RAW settings this
    publish deliberately did not ship; ``base_seed_guarded`` is the §5.1 answer
    specifically. The guard is reported even though (and precisely because) the
    projection makes the clobber structurally impossible — a silent skip is not
    accounting.

    ``bound_profiles`` arrives from the resolution pass, which reads it off the
    binding authority. It used to be recovered by reading ``hermes_profile`` back
    out of the projected bodies — so when the projection published partial
    bodies (2026-07-25) this row reported ``profiles_withheld: ["default"]`` and
    ``base_seed_guarded: false``, a false all-clear on the §5.1 guard produced by
    the very defect it was meant to watch. Accounting derived from the artifact
    it is accounting for cannot detect that the artifact is wrong.
    """

    return {
        **projection.as_dict(),
        "profiles_withheld": list(bound_profiles),
        "base_seed_guarded": BASE_PROFILE_NAME in bound_profiles,
    }


def _bound_profile_name(persona: AgentPersona) -> str:
    """The profile HOME this persona's files publish out of.

    Same authority and same fallback chain ``_persona_artifacts`` uses
    (``resolve_persona_profile`` → declared binding, else the active profile), so
    "profiles whose raw config.yaml was withheld" is exactly the set of profile
    homes this publish actually read from. Un-tokenized on purpose: this names a
    profile, not a published path segment.
    """

    binding = resolve_persona_profile(persona)
    return str(binding.hermes_profile or active_profile_name() or "default")


def _assert_no_raw_profile_config(artifacts: list[RealmSyncArtifact]) -> None:
    """Structural base-seed guard (Office plan §5.1), enforced for EVERY profile.

    §5.1 ruled the base profile — the machine seed every free profile forks from
    — must never travel: overwriting a member's fork seed changes every agent
    they create afterwards, including outside this realm. The original guard was
    written against the base PERSONA id, so a
    persona merely *bound to* ``hermes_profile: base`` walked past it and
    published ``profiles/base/config.yaml`` anyway.

    The rule is now structural and profile-agnostic: no raw profile
    ``config.yaml`` may ever be an artifact. Only allowlisted persona definitions
    leave, via the synthesized projection.
    """

    offenders = sorted(
        artifact.relative_path.replace("\\", "/")
        for artifact in artifacts
        if _is_raw_profile_config_path(artifact.relative_path.replace("\\", "/"))
    )
    if offenders:
        raise RealmSyncError(
            "sync_profile_config_excluded",
            "Realm sync refused to publish a raw profile config.yaml; only the "
            "portable persona-definition projection may travel.",
            safe_details={"paths": offenders, "base_profile": BASE_PROFILE_NAME},
        )


def _is_raw_profile_config_path(rel: str) -> bool:
    parts = Path(rel).parts
    return len(parts) == 3 and parts[0] == "profiles" and parts[2] == "config.yaml"


def _assert_portable_artifacts(artifacts: list[RealmSyncArtifact]) -> None:
    """Refuse to publish machine/installation-shaped values in CONFIGURATION.

    Scope is deliberate. This runs over the STRUCTURED persona-definition
    projection — parsed, key by key — not over free text. A skill's SKILL.md, a
    profile ``MEMORY.md``, or an ``AGENTS.md`` legitimately mentions absolute
    paths as prose; refusing those would brick every publish on this machine
    without protecting anything, and "a refusal that bricks a publish over a
    false positive" is a failure class this file has already paid for. What
    matters is that no absolute path ends up as live WIRING on another member's
    machine — and wiring only ever comes from the projection.

    Refuse rather than warn: the projection is synthesized under our own
    allowlist, so a machine-shaped value in it is a genuine authoring defect, and
    shipping it silently is exactly the bug being retired. ALL offenders are
    named in one typed error so an operator fixes them in a single pass.
    """

    from ..persona_config_sync import NONPORTABLE_HINT, find_nonportable_values, raw_persona_overrides

    offenders: list[dict[str, str]] = []
    for artifact in artifacts:
        if artifact.kind != "persona_config":
            continue
        try:
            data = yaml.safe_load(artifact.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        personas = data.get("personas") if isinstance(data, dict) else None
        if not isinstance(personas, dict):
            personas = raw_persona_overrides(data)
        for row in find_nonportable_values(personas, prefix="personas"):
            offenders.append({**row, "value": _redact_text(row["value"])})
    if offenders:
        raise RealmSyncError(
            "sync_nonportable_path",
            "Realm sync refused to publish machine-shaped values that cannot "
            "resolve on another member's machine.",
            safe_details={"offenders": offenders, "hint": NONPORTABLE_HINT},
        )


def _artifacts_from_subtree(subtree: Path) -> list[RealmSyncArtifact]:
    if not subtree.exists():
        return []
    artifacts: list[RealmSyncArtifact] = []
    for source in sorted(path for path in subtree.rglob("*") if path.is_file() and path.name != "manifest.json"):
        rel = source.relative_to(subtree).as_posix()
        destination = _destination_for_sync_path(rel)
        if destination is None:
            continue
        artifacts.append(RealmSyncArtifact(kind=_kind_for_sync_path(rel), source=source, relative_path=rel, destination=destination))
    return artifacts
