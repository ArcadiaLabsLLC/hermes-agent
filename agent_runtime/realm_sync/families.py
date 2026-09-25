"""Which sync family a published path belongs to, and where the generic pull may write it.

Pure path policy: ``_destination_for_sync_path`` (``None`` = an applier owns the
family), ``_kind_for_sync_path``, the per-profile home a token maps to, and the
secret/hard-excluded path predicates. Separate from ``pull`` so the importers that
read these (``profile_artifact_sync``, ``sync_admission``) reach a module that
imports no applier.
"""

from __future__ import annotations

import re
from pathlib import Path

from hermes_constants import get_hermes_home

from .. import paths
from ..profile_context import active_profile_name
from .models import HARD_EXCLUDED_PATH_PARTS, SECRET_PATH_MARKERS

__layer__ = "policy"
__all__ = [
    "_destination_for_sync_path",
    "_is_hard_excluded_path",
    "_is_secretish_path",
    "_kind_for_sync_path",
    "_profile_home_for_token",
]


def _destination_for_sync_path(rel: str) -> Path | None:
    parts = Path(rel).parts
    if parts and parts[0] == "skills":
        # Skills no longer overwrite the canonical shared root through the generic
        # pull loop. ``apply_skill_inbox_pull`` mirrors them into the
        # resolver-invisible per-realm inbox and admits them to the canonical root
        # only through the one guarded promotion door (C3) — same board/office
        # exclusion precedent (store/boards/*, store/office/* → None). Returning
        # None here keeps a realm pull from silently clobbering a local canonical
        # skill of the same id.
        return None
    if len(parts) == 3 and parts[0] == "store" and parts[1] == "workspaces":
        return paths.workspaces_dir() / parts[2]
    if len(parts) == 3 and parts[0] == "store" and parts[1] == "realms":
        return paths.realms_dir() / parts[2]
    # store/boards/* and store/office/* deliberately fall through to None: the
    # generic overwrite loop never touches them — board_sync.apply_board_pull /
    # office_sync.apply_office_pull own those pulls (3-way baseline merge).
    if parts and parts[0] == "store" and len(parts) == 2 and parts[1] == "personas.yaml":
        # The portable persona-definition projection. Owned by
        # ``persona_config_sync.apply_persona_config_pull`` (key-wise merge
        # against a never-synced baseline), never the generic overwrite loop —
        # same exclusion precedent as store/boards/*, store/office/*, skills/*.
        return None
    if parts and parts[0] == "store" and len(parts) == 2 and parts[1] == "persona_instances.yaml":
        # The portable persona-INSTANCE projection. Owned by
        # ``apply_persona_instance_pull`` (the mint door + the 3-way baseline
        # merge), never the generic overwrite loop: a raw write of this document
        # would put a persona-instance YAML somewhere no reader expects it, and
        # would produce replicas no live consumer ever heard about.
        #
        # It ALREADY resolved to None through the final fallthrough before this
        # branch existed (pinned by a test at the base sha), so this line changes
        # no behaviour — it records the OWNERSHIP, the way the personas.yaml
        # branch directly above does.
        return None
    if parts and parts[0] == "store" and len(parts) == 2 and parts[1] == "flow_graphs.yaml":
        # The portable CANVAS projection. Owned by ``apply_flow_graph_pull``
        # (adopt-or-hold at whole-document granularity against the 3-way
        # baseline), never the generic overwrite loop: a raw write would put a
        # multi-graph YAML where the store expects one JSON file per graph id,
        # and would bypass ``parse_flow_graph_doc`` — the validation every
        # stored canvas has passed through since the family existed.
        #
        # Like the branch above, this already resolved to None through the final
        # fallthrough; the line records the OWNERSHIP.
        return None
    if len(parts) == 3 and parts[0] == "store" and parts[1] == "levels":
        # The workspace LEVEL family. Owned by ``level_sync.apply_level_pull``
        # (adopt-or-hold at whole-document granularity against the 3-way
        # baseline), never the generic overwrite loop: a raw write would put a
        # peer's environment on this disk without passing the store door that
        # validates it, and it would do so on a LAST-WRITE-WINS basis over a
        # level this operator may have authored — the exact clobber the baseline
        # exists to refuse.
        #
        # Like the two branches above it this ALREADY resolved to None through
        # the final fallthrough (which is what made the launcher unable to do
        # this from its side at all); the line records the OWNERSHIP.
        return None
    if len(parts) == 3 and parts[0] == "store" and parts[1] == "maps":
        # The MAP CATALOGUE family. Owned by ``map_sync.apply_map_pull``
        # (adopt-or-hold at whole-document granularity against the 3-way
        # baseline), never the generic overwrite loop: a raw write would put a
        # peer's catalogue entry on this disk without passing the store door
        # that validates it — including the ``name`` check, which is the one
        # fact the whole family exists for — and it would do so LAST-WRITE-WINS
        # over an entry this operator may have renamed.
        #
        # Like the branch above it this ALREADY resolved to None through the
        # final fallthrough; the line records the OWNERSHIP.
        return None
    if len(parts) > 2 and parts[0] == "store" and parts[1] == "profile_files":
        # The per-profile FILE family (MEMORY.md, core context, persona prompts).
        # Owned by ``profile_artifact_sync.apply_profile_artifact_pull``.
        return None
    if parts and parts[0] == "profiles" and len(parts) > 1:
        # EVERY legacy ``profiles/…`` artifact is now owned by an applier, none
        # by the generic overwrite loop:
        #   - ``config.yaml``            → persona_config_sync (allowlisted merge)
        #   - memories / context / prompts → profile_artifact_sync (baseline merge)
        # Before 2026-07-25 the last four were written wholesale here, which
        # DESTROYED a member's accumulated ``MEMORY.md`` on every pull and keyed
        # prompt destinations by filename only (two personas on one profile
        # clobbered each other — Office plan §5.1). Same exclusion precedent as
        # store/boards/*, store/office/*, skills/*, store/personas.yaml.
        return None
    return None


def _profile_home_for_token(token: str) -> Path | None:
    """Profile-aware pull destination (W-H4, plan §5.1).

    Before 2026-07-17 this mapping collapsed EVERY ``profiles/<name>/…``
    artifact into the active profile home (a degenerate ternary — both
    branches returned ``get_hermes_home()``), so a multi-profile realm pull
    last-write-wins'd every profile's config.yaml/MEMORY.md onto one home.
    Now: the active profile keeps the active home; any other published profile
    resolves to ITS OWN home via ``get_profile_dir`` (materialized by the pull
    write-loop's mkdir and reported as a typed ``profile_sync`` row). Untrusted
    remote component: refuse traversal/absolute/drive-letter shapes.
    """

    if token in ("", ".", "..") or ":" in token or token.startswith(("/", "\\")):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", token):
        return None
    if token == paths.safe_path_token(active_profile_name()):
        return get_hermes_home()
    try:
        from hermes_cli.profiles import get_profile_dir, normalize_profile_name

        return get_profile_dir(normalize_profile_name(token))
    except Exception:
        return None


def _kind_for_sync_path(rel: str) -> str:
    if rel.startswith("skills/"):
        return "skill"
    if rel.startswith("store/workspaces/"):
        return "workspace"
    if rel.startswith("store/realms/"):
        return "realm"
    if rel.startswith("store/office/"):
        return "office_actor" if "/actors/" in rel else "office"
    if rel == "store/personas.yaml":
        return "persona_config"
    if rel == "store/persona_instances.yaml":
        return "persona_instance_config"
    if rel == "store/flow_graphs.yaml":
        return "flow_graph_config"
    if rel.startswith("store/levels/"):
        return "level"
    if rel.startswith("store/maps/"):
        return "map"
    if rel.startswith("store/profile_files/"):
        # Kind is derived from the DESTINATION the published tail names — the
        # same authority the pull applier uses, never a second spelling.
        from ..profile_artifact_sync import classify_destination

        tail = rel.split("/", 3)
        return (classify_destination(tail[3]) if len(tail) > 3 else None) or "artifact"
    if rel.endswith("config.yaml"):
        return "persona_config"
    if "/memories/" in rel:
        return "profile_memory"
    if "/context/" in rel:
        return "core_context"
    if "/system_prompt/" in rel:
        return "system_prompt"
    if "/soul_overlay/" in rel:
        return "soul_overlay"
    return "artifact"


def _is_secretish_path(rel: str) -> bool:
    parts = {part.lower() for part in Path(rel).parts}
    return bool(parts & SECRET_PATH_MARKERS)


def _is_hard_excluded_path(rel: str) -> bool:
    parts = {part.lower() for part in Path(rel).parts}
    return bool(parts & HARD_EXCLUDED_PATH_PARTS)
