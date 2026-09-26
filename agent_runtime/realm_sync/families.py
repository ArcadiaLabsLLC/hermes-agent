"""Which sync family a published path belongs to, and where the generic pull may write it.

Pure path policy: ``_destination_for_sync_path`` (``None`` = an applier owns the
family), ``_kind_for_sync_path``, the secret/hard-excluded path predicates, and
the profile-file destination vocabulary (``PROFILE_FILES_ROOT``,
``classify_destination``, ``entity_key``, ``published_relative_path``,
``content_hash``) that ``profile_artifact_sync``'s applier and the publish side
both read. The per-profile home a token maps to (``_profile_home_for_token``) needs the
active profile, so it lives in ``profile_context`` (stores). Separate from ``pull`` so the importers that
read these (``profile_artifact_sync``, ``sync_admission``) reach a module that
imports no applier.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from .. import paths
from .models import HARD_EXCLUDED_PATH_PARTS, SECRET_PATH_MARKERS

__layer__ = "policy"
__all__ = [
    "CORE_CONTEXT_FILENAMES",
    "GENERIC_PULL",
    "KIND_CORE_CONTEXT",
    "KIND_PERSONA_PROMPT",
    "KIND_PROFILE_MEMORY",
    "LEGACY_PROFILES_ROOT",
    "MEMORY_DESTINATION",
    "PERSONA_PROMPT_DIR",
    "PROFILE_FILES_ROOT",
    "SYNC_PATH_FAMILIES",
    "SyncFamily",
    "SyncPathFamily",
    "_LEGACY_PROFILE_FILE_KINDS",
    "_contains",
    "_destination_for_sync_path",
    "_exactly",
    "_is_hard_excluded_path",
    "_is_secretish_path",
    "_kind_for_sync_path",
    "_prefix",
    "_profile_file_kind",
    "_store_record",
    "classify_destination",
    "content_hash",
    "entity_key",
    "published_relative_path",
    "split_entity_key",
]


class SyncFamily(StrEnum):
    """ONE vocabulary for realm sync's families: every artifact kind a published
    path resolves to, and every store-drift family a revert row addresses.

    The values ARE wire contracts — artifact rows, publish notification counts,
    ``store_drift.items[].family`` and ``realm sync revert --item`` specs all
    carry them — so no value may change. That is why the office surface has two
    members: its artifact kind has always been ``office`` and its drift family
    ``office_surface``, and both spellings are on the wire. One enum holds both
    so neither is a free string any more.
    """

    SKILL = "skill"
    REALM = "realm"
    WORKSPACE = "workspace"
    BOARD = "board"
    BOARD_CARD = "board_card"
    OFFICE = "office"
    OFFICE_SURFACE = "office_surface"
    OFFICE_ACTOR = "office_actor"
    PERSONA_CONFIG = "persona_config"
    PERSONA_INSTANCE_CONFIG = "persona_instance_config"
    PERSONA_INSTANCE = "persona_instance"
    FLOW_GRAPH_CONFIG = "flow_graph_config"
    FLOW_GRAPH = "flow_graph"
    LEVEL = "level"
    MAP = "map"
    PROFILE_FILE = "profile_file"
    ARTIFACT = "artifact"


#: The loop in ``pull.pull_realm_sync`` that overwrites a destination wholesale.
#: Only the two store-record families still ride it; every other family's pull
#: is owned by an applier that merges against a never-synced baseline.
GENERIC_PULL = "pull.pull_realm_sync (generic overwrite loop)"


@dataclass(frozen=True, slots=True)
class SyncPathFamily:
    """One family's claim on a published path.

    ``match`` answers "is this path mine"; the FIRST matching row names the
    path's kind (``derive_kind`` when the kind is read off the path, else
    ``kind``, else the family itself). ``destination`` is where the generic pull
    loop may write the path — ``None`` for every family an applier owns, and
    ``owner`` names that applier, which is what the ``None`` means.
    """

    family: SyncFamily
    match: Callable[[str], bool]
    owner: str
    kind: str | None = None
    derive_kind: Callable[[str], str] | None = None
    destination: Callable[[tuple[str, ...]], Path | None] | None = None

    def kind_of(self, rel: str) -> str:
        if self.derive_kind is not None:
            return self.derive_kind(rel)
        return self.kind or self.family


def _prefix(prefix: str) -> Callable[[str], bool]:
    return lambda rel: rel.startswith(prefix)


def _exactly(path: str) -> Callable[[str], bool]:
    return lambda rel: rel == path


def _contains(needle: str) -> Callable[[str], bool]:
    return lambda rel: needle in rel


def _store_record(directory: Callable[[], Path], name: str) -> Callable[[tuple[str, ...]], Path | None]:
    """``store/<name>/<file>`` -> ``<directory>/<file>``: the one generic destination shape."""

    def destination(parts: tuple[str, ...]) -> Path | None:
        if len(parts) == 3 and parts[0] == "store" and parts[1] == name:
            return directory() / parts[2]
        return None

    return destination

# --- contract ---------------------------------------------------------------

#: Root of the published profile-file family. Unknown to every older client.
PROFILE_FILES_ROOT = "store/profile_files"

#: Legacy published root (an older publisher). Read on pull, never written.
LEGACY_PROFILES_ROOT = "profiles"

KIND_PROFILE_MEMORY = "profile_memory"
KIND_CORE_CONTEXT = "core_context"
KIND_PERSONA_PROMPT = "persona_prompt"

MEMORY_DESTINATION = "memories/MEMORY.md"
CORE_CONTEXT_FILENAMES: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
PERSONA_PROMPT_DIR = "personas"

#: Bound on an untrusted remote destination depth (a realm cannot make a member
#: materialize an arbitrarily deep tree).
_MAX_DESTINATION_DEPTH = 8

#: A prompt/overlay destination must be a text document. This — not a directory
#: prefix — is what keeps the prompt lane from reaching anything dangerous in a
#: profile home: ``config.yaml``, ``.env``, ``*.db``, ``plugins/**/*.py``,
#: ``skins/*.yaml`` all fail it. Restricting prompts to ``personas/**`` instead
#: was WRONG and shipped a silent one-way loss: ``soul_overlay_path`` and
#: ``system_prompt_path`` are profile-relative to ANYWHERE in the home
#: (``soul.md`` at the root is a real, supported shape — see
#: ``realm_sync._profile_relative_file``), so publish emitted ``soul.md`` and
#: pull refused it as ``destination_not_allowed``. Caught 2026-07-25 by the
#: rebind-delta suite; ``test_publish_and_pull_agree_on_every_destination`` is
#: the standing guard that the two sides can never disagree again.
_PROMPT_SUFFIXES: frozenset[str] = frozenset({".md", ".txt"})


def classify_destination(dest_rel: str) -> str | None:
    """The artifact kind a profile-relative destination denotes, or ``None`` when
    the destination is not admissible.

    This is the whole safety story for an untrusted remote path: without it a
    realm could publish ``config.yaml`` or ``.env`` into a member's profile home
    — the exact clobber class this module retires.

    Member-accumulated state is a CLOSED set of exactly four destinations
    (``memories/MEMORY.md`` + the three core-context files at the profile root),
    which is what makes the classification unambiguous without a kind marker in
    the path. Everything else is a prompt/overlay, admitted only as a text
    document (:data:`_PROMPT_SUFFIXES`) that is not shadowing a member-state
    destination and carries no hidden/dot component.
    """

    text = str(dest_rel or "").replace("\\", "/").strip("/")
    if not text:
        return None
    parts = tuple(text.split("/"))
    if len(parts) > _MAX_DESTINATION_DEPTH:
        return None
    if any(not part or part.startswith(".") for part in parts):
        return None
    if text == MEMORY_DESTINATION:
        return KIND_PROFILE_MEMORY
    if len(parts) == 1 and parts[0] in CORE_CONTEXT_FILENAMES:
        return KIND_CORE_CONTEXT
    # A prompt may not shadow a member-state destination: ``memories/anything``
    # and a core-context filename at the root belong to the closed set above, and
    # a prompt-kind write must never be able to reach them.
    if parts[0] == "memories" or (len(parts) == 1 and parts[0] in CORE_CONTEXT_FILENAMES):
        return None
    if Path(parts[-1]).suffix.lower() in _PROMPT_SUFFIXES:
        return KIND_PERSONA_PROMPT
    return None


def entity_key(profile_token: str, dest_rel: str) -> str:
    """The merge unit: one DESTINATION on one profile home.

    Keyed on the destination — not on the persona — on purpose. Several personas
    on one profile publish the SAME ``MEMORY.md``/``AGENTS.md`` file; they must
    reconcile as one entity, not race each other. And two personas whose prompts
    would land on one path are then structurally visible as a collision rather
    than a silent last-write-wins.
    """

    return f"{profile_token}:{str(dest_rel).replace(chr(92), '/')}"


def split_entity_key(key: str) -> tuple[str, str] | None:
    profile, sep, dest = str(key or "").partition(":")
    if not sep or not profile or not dest:
        return None
    return profile, dest


def published_relative_path(profile_token: str, dest_rel: str) -> str:
    return f"{PROFILE_FILES_ROOT}/{profile_token}/{str(dest_rel).replace(chr(92), '/')}"


def content_hash(data: bytes) -> str:
    """Semantic content hash: EOL-canonical so a member's CRLF file and a
    publisher's LF artifact converge instead of conflicting forever."""

    from agent_runtime.realm_sync.models import _canonicalize_text_bytes

    return hashlib.sha256(_canonicalize_text_bytes(data)).hexdigest()


def _profile_file_kind(rel: str) -> str:
    """Kind is derived from the DESTINATION the published tail names — the
    same authority the pull applier uses, never a second spelling."""

    tail = rel.split("/", 3)
    return (classify_destination(tail[3]) if len(tail) > 3 else None) or SyncFamily.ARTIFACT


#: The pre-2026-07-25 ``profiles/<profile>/…`` layout's per-file kinds, matched
#: by path segment in this order. These are profile-FILE kinds, not families:
#: the family is ``PROFILE_FILE`` and its applier owns every one of them.
_LEGACY_PROFILE_FILE_KINDS = (
    ("/memories/", "profile_memory"),
    ("/context/", "core_context"),
    ("/system_prompt/", "system_prompt"),
    ("/soul_overlay/", "soul_overlay"),
)

#: Every published path's family, in match order. Rule 12's table for the two
#: ladders that used to answer this (``_destination_for_sync_path``,
#: ``_kind_for_sync_path``): the ownership comments those ladders carried are
#: the ``owner`` column now, and the only generic destinations are the two rows
#: that have one.
SYNC_PATH_FAMILIES: Final[tuple[SyncPathFamily, ...]] = (
    # Skills never overwrite the canonical shared root through the generic loop:
    # they mirror into the resolver-invisible per-realm inbox and reach the
    # canonical root only through the one guarded promotion door (C3), so a
    # realm pull cannot silently clobber a local canonical skill of the same id.
    SyncPathFamily(SyncFamily.SKILL, _prefix("skills/"), owner="skill_inbox.apply_skill_inbox_pull"),
    SyncPathFamily(
        SyncFamily.WORKSPACE,
        _prefix("store/workspaces/"),
        owner=GENERIC_PULL,
        destination=_store_record(paths.workspaces_dir, "workspaces"),
    ),
    SyncPathFamily(
        SyncFamily.REALM,
        _prefix("store/realms/"),
        owner=GENERIC_PULL,
        destination=_store_record(paths.realms_dir, "realms"),
    ),
    # store/office/* and store/boards/* are 3-way baseline merges; the generic
    # loop never touches them. (Boards have no kind row: a board path's kind was
    # never asked for, because nothing but the applier reads it.)
    SyncPathFamily(
        SyncFamily.OFFICE_ACTOR,
        lambda rel: rel.startswith("store/office/") and "/actors/" in rel,
        owner="office_sync.apply_office_pull",
    ),
    SyncPathFamily(SyncFamily.OFFICE, _prefix("store/office/"), owner="office_sync.apply_office_pull"),
    # The portable persona-definition projection: a key-wise merge against a
    # never-synced baseline.
    SyncPathFamily(
        SyncFamily.PERSONA_CONFIG,
        _exactly("store/personas.yaml"),
        owner="persona_config_sync.apply_persona_config_pull",
    ),
    # The persona-INSTANCE projection: the mint door plus the 3-way merge. A raw
    # write would produce replicas no live consumer ever heard about.
    SyncPathFamily(
        SyncFamily.PERSONA_INSTANCE_CONFIG,
        _exactly("store/persona_instances.yaml"),
        owner="persona_instance_sync.apply_persona_instance_pull",
    ),
    # The CANVAS projection: adopt-or-hold per document. A raw write would put a
    # multi-graph YAML where the store expects one JSON per graph id, bypassing
    # ``parse_flow_graph_doc``.
    SyncPathFamily(
        SyncFamily.FLOW_GRAPH_CONFIG,
        _exactly("store/flow_graphs.yaml"),
        owner="flow_graph_sync.apply_flow_graph_pull",
    ),
    # The workspace LEVEL and the MAP CATALOGUE: whole-document adopt-or-hold. A
    # raw write would land a peer's document without its store door's validation,
    # last-write-wins over one this operator may have authored or renamed.
    SyncPathFamily(SyncFamily.LEVEL, _prefix("store/levels/"), owner="level_sync.apply_level_pull"),
    SyncPathFamily(SyncFamily.MAP, _prefix("store/maps/"), owner="map_sync.apply_map_pull"),
    SyncPathFamily(
        SyncFamily.PROFILE_FILE,
        _prefix("store/profile_files/"),
        owner="profile_artifact_sync.apply_profile_artifact_pull",
        derive_kind=_profile_file_kind,
    ),
    # EVERY legacy ``profiles/…`` artifact is owned by an applier. Before
    # 2026-07-25 the generic loop wrote them wholesale, which DESTROYED a member's
    # accumulated ``MEMORY.md`` on every pull and keyed prompts by filename only
    # (two personas on one profile clobbered each other — Office plan §5.1).
    SyncPathFamily(
        SyncFamily.PERSONA_CONFIG,
        lambda rel: rel.endswith("config.yaml"),
        owner="persona_config_sync.apply_persona_config_pull",
    ),
    *(
        SyncPathFamily(
            SyncFamily.PROFILE_FILE,
            _contains(needle),
            owner="profile_artifact_sync.apply_profile_artifact_pull",
            kind=kind,
        )
        for needle, kind in _LEGACY_PROFILE_FILE_KINDS
    ),
)


def _destination_for_sync_path(rel: str) -> Path | None:
    """Where the generic pull loop may write ``rel``: the one destination-bearing
    row that claims it, else ``None`` — which always means an applier owns the
    family (``SyncPathFamily.owner`` names it)."""

    parts = Path(rel).parts
    for family in SYNC_PATH_FAMILIES:
        if family.destination is not None:
            target = family.destination(parts)
            if target is not None:
                return target
    return None


def _kind_for_sync_path(rel: str) -> str:
    """The kind of the first family whose ``match`` claims ``rel``, else ``artifact``."""

    for family in SYNC_PATH_FAMILIES:
        if family.match(rel):
            return family.kind_of(rel)
    return SyncFamily.ARTIFACT


def _is_secretish_path(rel: str) -> bool:
    parts = {part.lower() for part in Path(rel).parts}
    return bool(parts & SECRET_PATH_MARKERS)


def _is_hard_excluded_path(rel: str) -> bool:
    parts = {part.lower() for part in Path(rel).parts}
    return bool(parts & HARD_EXCLUDED_PATH_PARTS)
