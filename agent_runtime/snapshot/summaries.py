"""Workspace, realm, agent and available-persona summaries, the profile
template memo, and repo-scope labels.
"""

from __future__ import annotations

import re
import threading
import time

from agent_runtime.profile_home import (
    available_profile_template_summaries as available_profile_templates,
)
from agent_runtime import paths
from agent_runtime.persona_assignments import persona_instance_visibility_ref
from agent_runtime.persona_chat_history.vocabulary import _SECRET_RE
from agent_runtime.personas import effective_toolsets
from agent_runtime.realm_sync.sidecar import read_realm_sync_sidecar
from agent_runtime.repo_context import resolve_affected_repo_workdir
from agent_runtime.tool_visibility import (
    _profile_readiness_for_visibility,
    resolve_tool_visibility,
)
from agent_runtime.workspace_scope import exact_scoped_instance_ids

from agent_runtime.snapshot.context import logger

__layer__ = "stores"

__all__ = [
    "_PROFILE_TEMPLATE_TTL_SECONDS",
    "_agent_summary",
    "_available_persona_summary",
    "_display_name_for_profile",
    "_maybe_reconcile_profile_personas",
    "_profile_persona_reconcile_lock",
    "_profile_persona_reconcile_tick",
    "_profile_template_memo",
    "_profile_templates_cached",
    "realm_summary",
    "_repo_scope_entry",
    "_repo_scopes_summary",
    "_safe_model_label",
    "_safe_repo_scope_label",
    "_safe_text",
    "workspace_summary",
]


def workspace_summary(
    workspace,
    *,
    persona_instances=(),
    active_id: str | None = None,
) -> dict:
    roster_agent_ids = list(workspace.agent_ids or [])
    live_scoped_agent_ids = exact_scoped_instance_ids(
        persona_instances,
        workspace_id=workspace.id,
    )
    return {
        "id": workspace.id,
        "kind": "workspace",
        "name": workspace.name,
        "slug": workspace.slug,
        "realm_id": workspace.realm_id,
        # Keep the legacy ``agents``/``agent_ids`` pair internally coherent:
        # both describe exact live rows placed in this workspace.  Emitting
        # roster persona ids here made pointerless canonical operator rows look
        # workspace-scoped to older consumers, duplicating each real placement.
        # Persisted roster metadata remains available under the explicit
        # ``roster_agent_*`` contract.
        "agents": len(live_scoped_agent_ids),
        "agent_ids": live_scoped_agent_ids,
        "live_scoped_agent_count": len(live_scoped_agent_ids),
        "live_scoped_agent_ids": live_scoped_agent_ids,
        "roster_agent_count": len(roster_agent_ids),
        "roster_agent_ids": roster_agent_ids,
        # S47 removed ``"goals": len(goals)``. It counted an always-empty seed,
        # so the wire published a permanent 0 that the Launcher rendered as a
        # count and gated workspace deletion on (ledger item 5).
        "isolation": workspace.isolation,
        "max_concurrent_lanes": workspace.max_concurrent_lanes,
        "default_blueprint_id": workspace.default_blueprint_id,
        "archived": bool(workspace.archived),
        "active": workspace.id == active_id,
        "updated_at": workspace.updated_at,
    }


def realm_summary(realm, *, workspaces, active_id: str | None = None) -> dict:
    workspace_ids = [workspace.id for workspace in workspaces if getattr(workspace, "realm_id", None) == realm.id]
    configured_ids = list(getattr(realm, "workspace_ids", []) or [])
    merged_ids = list(dict.fromkeys([*configured_ids, *workspace_ids]))
    return {
        "id": realm.id,
        "kind": "realm",
        "name": realm.name,
        "slug": realm.slug,
        "server_id": realm.server_id,
        "default_workspace_id": getattr(realm, "default_workspace_id", None),
        "default_workspace_name": getattr(realm, "default_workspace_name", "Default"),
        "default_workspace_version": getattr(realm, "default_workspace_version", 0),
        "workspaces": len(merged_ids),
        "workspace_ids": merged_ids,
        # Stage 43 (Decision 7): sync state comes ONLY from the cached sidecar
        # written by the `realm sync status|pull|publish` verbs — build_snapshot
        # must never shell out to git or resolve artifacts. Absent sidecar →
        # null so the launcher renders "not checked", not a fake in_sync.
        "sync": read_realm_sync_sidecar(realm.id),
        "archived": bool(realm.archived),
        "active": realm.id == active_id,
        "updated_at": realm.updated_at,
    }


def _agent_summary(agent, *, include_tool_details: bool = False, readiness=None):
    # Route through the same TTL-memoized readiness resolve_tool_visibility uses
    # (below) instead of a direct profile_readiness_for_persona call, so one build
    # computes readiness at most once per agent instead of twice. Identical result
    # for this path: readiness is task/stage-independent here, and the memo shares
    # the exact inputs (id/profile/skills/mcp/provider/model/api_mode).
    if readiness is None:
        readiness = _profile_readiness_for_visibility(agent)
    tool_resolution = resolve_tool_visibility(agent, profile_readiness=readiness)
    summary = {
        "persona_id": agent.id,
        "display_name": agent.display_name,
        "role": agent.role,
        "hermes_profile": agent.hermes_profile,
        "profile_readiness": readiness["readiness"],
        "readiness_summary": readiness["summary"],
        "skills": list(agent.skills),
        "missing_skills": readiness.get("missing_skills", []),
        "required_mcp_servers": list(agent.required_mcp_servers),
        "effective_required_mcp_servers": readiness.get("effective_required_mcp_servers", []),
        "missing_mcp_servers": readiness.get("missing_mcp_servers", []),
        "skill_hash_mismatches": readiness.get("skill_hash_mismatches", []),
        # ABSENT is not MATCHING (H-H7): readiness has published the split since
        # the hash-states lane landed, but this row copied only the mismatch
        # half, so no frame the launcher ever received could tell "the two
        # copies agreed" from "there is no installed copy to compare".
        "skill_hash_absent": readiness.get("skill_hash_absent", []),
        # The DECLARED lane set (S0a A1 moved the authority into
        # ``effective_toolsets``): the launcher's agent card "Toolsets" tag block
        # became truthful with no launcher change, because this row stopped
        # projecting a per-persona list no admission path reads.
        "toolsets": effective_toolsets(agent),
        "model_configured": bool(agent.model),
        "provider_configured": bool(agent.provider),
        "default_model": _safe_model_label(getattr(agent, "model", None)),
        "default_provider": _safe_model_label(getattr(agent, "provider", None)),
        "autonomy": agent.autonomy,
        "core_context_files": "enabled" if getattr(agent, "include_core_context_files", False) else "isolated",
        "repo_scope_label": _safe_text(getattr(agent, "repo_scope_label", None)) or _safe_repo_scope_label(getattr(agent, "repo_scope", None)),
    }
    if include_tool_details:
        # Deferred: ``tool_permissions`` imports ``tool_visibility``, which this
        # module already imports at load time; keeping the reader local avoids
        # widening the module-load graph for one scalar fallback.
        from ..tool_permissions import default_permission_mode

        # Residue-slim R2: same tool-detail eviction as persona_instance_summary.
        # The heavy payloads (tool_resolution / turn_tool_context /
        # permission_state / blocked_tools) leave the row behind a typed
        # ``visibility_ref`` pointer, fetched on demand via
        # ``harness persona-instance detail``; ``agent_hud_state`` is RETIRED
        # (runtime_hud.py is the single HUD authority). The head keeps only the
        # SCALARS the agents drawer renders, derived at emit from the same
        # tool-visibility resolution.
        summary.update(
            {
                # Fallback follows the RUNTIME DEFAULT, not a bounded literal: the
                # agents drawer must not render a posture no turn actually runs
                # under (2026-08-09 ruling). ``blocked_tools_count`` moves 22 → 17
                # under the unbounded default — the registry-hygiene names, which
                # never yield to a mode.
                "permission_mode": tool_resolution.get("permission_mode") or default_permission_mode(),
                "mutation_boundary": tool_resolution["mutation_boundary"],
                "tool_count": tool_resolution["final_tool_count"],
                "blocked_tools_count": len(tool_resolution["blocked_tools"]),
                "effective_toolsets": tool_resolution["effective_toolsets"],
                "visibility_ref": persona_instance_visibility_ref(agent.id),
            }
        )
    return summary


# Profile-template discovery re-parses every profile YAML (~0.7s of one
# snapshot core, measured 2026-07-09) and the catalog changes only when the
# operator installs/creates a profile. Same TTL-memo treatment as the skill
# catalog in prompt_observability — observability rows, never authority; a
# new profile appears on the first core built after the TTL lapses.
_PROFILE_TEMPLATE_TTL_SECONDS = 15.0


_profile_template_memo: dict = {"at": 0.0, "rows": None, "fn": None}


_profile_persona_reconcile_lock = threading.Lock()


_profile_persona_reconcile_tick: dict = {"root": None, "at": 0.0}


def _maybe_reconcile_profile_personas() -> None:
    """Admit new local profiles at most once per root per discovery window.

    A failed scan does not advance the tick, so the next snapshot retries.
    Other snapshot paths still work, with the failure visible in runtime logs.
    """
    root = str(paths.store_root())
    with _profile_persona_reconcile_lock:
        at = time.monotonic()
        if (
            root == _profile_persona_reconcile_tick["root"]
            and at - _profile_persona_reconcile_tick["at"] < _PROFILE_TEMPLATE_TTL_SECONDS
        ):
            return
        try:
            from ..profile_persona_discovery import reconcile_profile_personas

            reconcile_profile_personas()
        except Exception:
            logger.exception("Named Hermes profile auto-discovery failed")
            return
        _profile_persona_reconcile_tick.update(root=root, at=at)


def _profile_templates_cached() -> list:
    """Memo keyed on BOTH the TTL and the fetcher's identity: a
    monkeypatched `available_profile_templates` invalidates the memo
    immediately instead of being masked for a TTL window."""
    import time

    fetcher = available_profile_templates
    now = time.monotonic()
    if (
        _profile_template_memo["rows"] is not None
        and _profile_template_memo["fn"] is fetcher
        and now - _profile_template_memo["at"] < _PROFILE_TEMPLATE_TTL_SECONDS
    ):
        return _profile_template_memo["rows"]
    try:
        rows = list(fetcher())
    except Exception:
        rows = []
    _profile_template_memo["rows"] = rows
    _profile_template_memo["at"] = now
    _profile_template_memo["fn"] = fetcher
    return rows


def _available_persona_summary(agents) -> list[dict]:
    """One placeable row per profile template, carrying the spellings that work.

    The launcher's Presets lane takes ``persona_id`` off these rows verbatim
    into ``runtime.agent.create`` -> ``--persona``, so a row that advertises a
    spelling the CLI's own authority withholds places something the operator did
    not choose. ``profile:<name>`` is exactly such a spelling for a profile that
    TWO personas declare: it still parses (decision D-U1 exempts every
    ``profile:`` id from the roster check) but ``profile_persona_resolution``
    returns no match for an ambiguously-owned profile, so the resolver
    synthesises a persona with config defaults and NO toolsets — a different
    agent from the id printed beside it.

    So the spellings come from :func:`agent_create.accepted_persona_spellings`,
    the one authority for "how may an operator name this row", asked once per
    OWNER of the profile. Three shapes fall out of that, and the third is why
    this function still has to think:

    * two or more owners — the authority answers each owner's bare id and
      withholds ``profile:<name>``, so the row advertises the ids and not the
      profile spelling.
    * exactly one owner — bare id first, then ``profile:<name>``, which inherits
      that owner's defaults.
    * no owner at all — the template-only placement lane the launcher's library
      exists for. The per-persona authority cannot answer it (there is no
      persona to key on) and its synthesis is INTENDED here, so the row supplies
      ``profile:<name>`` itself and the list is never empty.

    ``backs_persona_id`` follows the same rule for the same reason. It used to
    be built by a dict comprehension keyed on profile name, which silently kept
    whichever owner iterated LAST; a row that names one of two owners as the
    persona it places is the same lie in a different field.
    """

    templates = _profile_templates_cached()
    if not templates:
        return []
    # Local import: ``agent_create`` reaches into the CLI's persona resolver,
    # and snapshot builds must not pay that import when there are no templates.
    from ..agent_create.request import accepted_persona_spellings

    roster = list(agents or [])
    owners_by_profile: dict[str, list] = {}
    for agent in roster:
        profile = str(getattr(agent, "hermes_profile", "") or "").strip()
        persona_id = str(getattr(agent, "id", "") or "").strip()
        if profile and persona_id:
            owners_by_profile.setdefault(profile, []).append(agent)
    summaries: list[dict] = []
    for template in templates:
        profile_name = str(getattr(template, "name", "") or "").strip()
        if not profile_name:
            continue
        item = {
            "persona_id": f"profile:{profile_name}",
            "display_name": _display_name_for_profile(profile_name),
            "role": "profile",
            "hermes_profile": profile_name,
            "source": "hermes_profile",
            "template_only": True,
            "profile_readiness": "available",
        }
        description = _safe_text(str(getattr(template, "description", "") or ""))
        if description:
            item["description"] = description
        owners = owners_by_profile.get(profile_name, [])
        spellings: list[str] = []
        for owner in owners:
            for spelling in accepted_persona_spellings(owner, roster):
                if spelling and spelling not in spellings:
                    spellings.append(spelling)
        item["persona_spellings"] = spellings or [item["persona_id"]]
        if len(owners) == 1:
            item["backs_persona_id"] = str(getattr(owners[0], "id", "") or "")
        summaries.append(item)
    return summaries


def _display_name_for_profile(profile_name: str) -> str:
    words = [part for part in re.split(r"[-_\s]+", profile_name.strip()) if part]
    return " ".join(part[:1].upper() + part[1:] for part in words) or profile_name


def _safe_repo_scope_label(value):
    if not value:
        return None
    text = str(value).replace("\\", "/").rstrip("/")
    name = text.rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-._")[:64] or None


def _safe_model_label(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:/@+-]{1,220}", text):
        return None
    return text


def _repo_scopes_summary() -> dict:
    return {
        "harness": _repo_scope_entry("hermes-agent"),
        "frontend": _repo_scope_entry("EterniaLauncher"),
        "backend": _repo_scope_entry("EterniaBackend"),
    }


def _repo_scope_entry(alias: str) -> dict:
    resolved = resolve_affected_repo_workdir(alias)
    return {
        "label": _safe_repo_scope_label(alias),
        "resolved": resolved is not None,
    }


def _safe_text(value):
    """Operator-console text: paths allowed, secret assignments masked in place.

    This used to drop the ENTIRE string when it looked path-ish, which silently
    nulled dev decision rationales/summaries (any real dev rationale names a
    file) and starved the conversation projection of thinking/turn detail.
    Mission Control is an operator surface: repo paths are the content, not a
    leak. Only secret-shaped assignments are redacted, and in place.
    """

    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text:
        return None
    text = _SECRET_RE.sub("[redacted secret]", text)
    if len(text) > 500:
        return f"{text[:497]}…"
    return text
