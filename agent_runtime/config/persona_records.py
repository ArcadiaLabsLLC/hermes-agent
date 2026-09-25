"""Persona records declared in config, and their merge with the persisted persona store.

Map: ``agent_runtime/config/__init__.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..personas import PROFILE_ROLE_SENTINEL, validate_toolsets
from ..serde import positive_float, positive_int
from .loader import load_agent_runtime_config
from .schema import AgentRuntimeConfig
from .sections import _string_list

logger = logging.getLogger(__name__)

__layer__ = "policy"


def _expand_machine_root_tokens(value, *, field: str):
    """Expand ``${roots.…}`` in a persona path field at config-load time.

    Unresolvable tokens are left LITERAL on purpose: substituting a guess would
    hand a persona a fabricated workdir, and blanking the field would look like
    "no repo scope configured". The literal token is the signal
    ``profile_readiness`` turns into a typed ``mcp_attention`` row with the
    exact `hermes harness roots set …` fix, and it can never be mistaken for a
    real path. Values with no token are returned unchanged.
    """

    from ..machine_roots import MachineRootError, contains_path_tokens, expand_config_paths

    if not contains_path_tokens(value):
        return value
    try:
        return expand_config_paths(value, field=field)
    except MachineRootError as exc:
        logger.error("Persona path field %s is unresolved: %s | fix: %s", field, exc.summary, exc.fix_hint)
        return value


def persona_records_from_config(cfg: AgentRuntimeConfig | None = None):
    cfg = cfg or load_agent_runtime_config()
    personas = {}
    for pid, overrides in cfg.personas.items():
        persona_id = str(pid or "").strip()
        if not persona_id or not isinstance(overrides, dict):
            continue
        if persona_id not in personas:
            role = str(overrides.get("role") or PROFILE_ROLE_SENTINEL)
            personas[persona_id] = _persona_from_overrides(persona_id, role, overrides, cfg)
        p = personas[persona_id]
        if "role" in overrides:
            p.role = str(overrides.get("role") or p.role)
        p.display_name = str(overrides.get("display_name", p.display_name))
        p.provider = overrides.get("provider", p.provider)
        p.model = overrides.get("model", p.model)
        p.api_mode = overrides.get("api_mode", p.api_mode)
        p.autonomy = str(overrides.get("autonomy", p.autonomy))
        p.hermes_profile = overrides.get("hermes_profile", p.hermes_profile)
        p.soul_overlay_path = overrides.get("soul_overlay_path", p.soul_overlay_path)
        p.include_profile_memory = bool(overrides.get("include_profile_memory", p.include_profile_memory))
        p.include_core_context_files = bool(overrides.get("include_core_context_files", p.include_core_context_files))
        p.repo_scope = _expand_machine_root_tokens(
            overrides.get("repo_scope", p.repo_scope),
            field=f"agent_runtime.personas.{persona_id}.repo_scope",
        )
        p.repo_scope_label = overrides.get("repo_scope_label", p.repo_scope_label)
        p.iteration_budget = positive_int(overrides.get("iteration_budget", p.iteration_budget))
        p.max_wall_seconds = positive_float(overrides.get("max_wall_seconds", p.max_wall_seconds))
        p.max_api_calls = positive_int(overrides.get("max_api_calls", p.max_api_calls))
        p.max_total_tokens = positive_int(overrides.get("max_total_tokens", p.max_total_tokens))
        if "skills" in overrides or "skills_remove" in overrides:
            additions = _string_list(overrides.get("skills", []))
            removals = set(_string_list(overrides.get("skills_remove", [])))
            # Persona defaults are required/recommended assignments. Config
            # extends that baseline by id; subtraction is explicit so adding
            # one skill never accidentally erases every default.
            merged = list(dict.fromkeys([*p.skills, *additions]))
            p.skills = [skill_id for skill_id in merged if skill_id not in removals]
        if "required_mcp_servers" in overrides:
            p.required_mcp_servers = _string_list(overrides["required_mcp_servers"])
        if "toolsets" in overrides:
            # STILL READ, deliberately (S0a A2): deleting the reader would make a
            # config that carries the key silently identical to one that never
            # did, and the realm-sync body would keep shipping a list nothing in
            # the runtime could even show. What changed is that the field admits
            # nothing — the harness lane reads the PROFILE's declaration
            # (``personas.declared_lane_toolsets``) — so a non-empty list is
            # announced once per load and reported in every projection as
            # ``toolset_declaration.persona_list``, never obeyed.
            p.toolsets = validate_toolsets(list(overrides["toolsets"]))
            if p.toolsets:
                logger.info(
                    "agent_runtime.personas.%s.toolsets is legacy and admits nothing "
                    "(S0a atlas cleanup): %s. The harness lane reads the bound "
                    "profile's top-level toolsets: key; delete this list.",
                    persona_id,
                    ", ".join(p.toolsets),
                )
    return list(personas.values())


def persona_skill_sources(cfg: AgentRuntimeConfig | None = None) -> dict[str, dict[str, Any]]:
    """Which tier answered each persona's ``skills``, and what the config lost.

    S0a A6c — ACCOUNTING ONLY, no write. The persona→skill seed row asked why a
    config ``skills:`` addition does not reach a placement. The mechanism is the
    same store-wins merge as toolsets (``ensure_persisted_personas`` merges
    ``{**catalog, **stored}``), but the ANSWER is different and does not
    transfer: skills have a store-writing verb with its own supersede clock
    (``persona set-skills`` → ``AgentPersona.skills_override_issued_at``) and the
    launcher's Skills console writes through it, so for skills the STORE is the
    authority BY DESIGN. A config-side seed that won over it would reintroduce
    the two-writer problem that clock exists to arbitrate.

    So this stage ships visibility instead of a new writer: ``skills_source``
    says which tier the effective list came from, and ``catalog_only_skills``
    names the config entries the store row does not carry — the silent
    difference an operator previously had to diff two files to see.
    """

    from ..store import AgentStore

    cfg = cfg or load_agent_runtime_config()
    stored = {persona.id: persona for persona in AgentStore().list_all()}
    catalog = {persona.id: persona for persona in persona_records_from_config(cfg)}
    rows: dict[str, dict[str, Any]] = {}
    for persona_id in set(stored) | set(catalog):
        stored_row = stored.get(persona_id)
        catalog_row = catalog.get(persona_id)
        effective = list(getattr(stored_row or catalog_row, "skills", []) or [])
        declared = list(getattr(catalog_row, "skills", []) or []) if catalog_row else []
        rows[persona_id] = {
            "skills_source": "store" if stored_row is not None else "catalog",
            "catalog_only_skills": [name for name in declared if name not in effective],
        }
    return rows


def ensure_persisted_personas(cfg: AgentRuntimeConfig | None = None):
    """Return the persisted persona store plus data-declared config records."""
    from ..store import AgentStore

    cfg = cfg or load_agent_runtime_config()
    store = AgentStore()
    stored = {persona.id: persona for persona in store.list_all()}
    catalog = {persona.id: persona for persona in persona_records_from_config(cfg)}
    merged = {**catalog, **stored}
    return list(merged.values())


def _persona_from_overrides(persona_id: str, role: str, overrides: dict[str, Any], cfg: AgentRuntimeConfig):
    from ..models import AgentPersona

    return AgentPersona(
        id=persona_id,
        display_name=str(overrides.get("display_name") or persona_id.replace("_", " ").title()),
        role=role,
        model=overrides.get("model") or cfg.default_model,
        provider=overrides.get("provider") or cfg.default_provider,
        api_mode=overrides.get("api_mode") or cfg.default_api_mode,
        toolsets=validate_toolsets(list(overrides.get("toolsets") or [])),
        system_prompt_path=str(overrides.get("system_prompt_path") or ""),
        include_core_context_files=bool(overrides.get("include_core_context_files", False)),
    )
