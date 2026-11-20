"""Persona records declared in config, and their merge with a persisted roster the caller passes in.

Map: ``agent_runtime/config/__init__.py``. The store READ is ``config.roster``
(``stores``); everything here takes the roster as an argument.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ..personas import PROFILE_ROLE_SENTINEL, DeclarationIssue, DeclarationIssueKind
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


#: The keys that make an ``agent_runtime.personas.<id>`` entry DECLARE an agent: who it is
#: (``role``, ``display_name``), what it runs as (``hermes_profile``, ``system_prompt_path``,
#: ``soul_overlay_path``) or what it was made from (``based_on``). Every body a realm pull
#: writes for a config-declared agent carries ``role`` and ``display_name`` (its projection
#: is built from a record, which always has both). An entry with none of these is a SETTING
#: for that id (``chat_lane_restore_toolsets``, skills, model, budgets, autonomy, repo
#: scope…): it overlays the stored record or the declaring entry of the id and declares
#: nothing alone (RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT, seen
#: 2026-11-19: a lone ``chat_lane_restore_toolsets`` under ``profile_base`` listed
#: "Profile Base" and minted its channel). The knobs themselves are read from config by id
#: (``config.chat_lane_restore_toolsets``), never through this roster.
PERSONA_IDENTITY_KEYS: frozenset[str] = frozenset(
    {"role", "display_name", "hermes_profile", "system_prompt_path", "soul_overlay_path", "based_on"}
)


def config_entry_declares_persona(overrides: Any) -> bool:
    """True when a config persona entry declares an agent, not only a setting for its id."""

    return isinstance(overrides, dict) and any(key in overrides for key in PERSONA_IDENTITY_KEYS)


def persona_records_from_config(cfg: AgentRuntimeConfig | None = None):
    """The agents ``config.yaml`` DECLARES (:data:`PERSONA_IDENTITY_KEYS`), as persona records.

    A settings-only entry lists nothing here; over a stored record the store wins the
    merge anyway, and the settings it carries are read by id where they apply.
    """

    cfg = cfg or load_agent_runtime_config()
    declared = _declared_ids(cfg)
    return [
        record
        for record in _records_from_config(cfg)
        # MUTATION: drop this filter and
        # test_a_setting_for_an_id_no_record_holds_lists_no_agent_and_mints_no_channel reddens.
        if record.id in declared
    ]


def _declared_ids(cfg: AgentRuntimeConfig) -> set[str]:
    return {
        str(pid or "").strip()
        for pid, overrides in cfg.personas.items()
        if config_entry_declares_persona(overrides)
    }


def _records_from_config(cfg: AgentRuntimeConfig):
    """Every config persona entry as a record, settings-only entries included."""

    personas = {}
    for pid, overrides in cfg.personas.items():
        persona_id = str(pid or "").strip()
        if not persona_id or not isinstance(overrides, dict):
            continue
        # The legacy key is never read below; a refusal is a typed issue row
        # (``legacy_persona_toolsets_issues``), never a raise out of this read.
        _log_legacy_toolsets_key_once(persona_id, overrides)
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
        p.character_assignment = overrides.get("character_assignment", p.character_assignment)
        based_on = overrides.get("based_on")
        p.based_on = dict(based_on) if isinstance(based_on, dict) else p.based_on
        p.autonomy = _autonomy(persona_id, overrides.get("autonomy", p.autonomy), p.autonomy)
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
    return list(personas.values())


LEGACY_PERSONA_TOOLSETS_KEY = "toolsets"

_LOGGED_LEGACY_KEYS: set[str] = set()


def _legacy_key(persona_id: str) -> str:
    return f"agent_runtime.personas.{persona_id}.{LEGACY_PERSONA_TOOLSETS_KEY}"


def legacy_persona_toolsets_issues(
    personas: Mapping[str, Any] | None,
    *,
    persona_id: str | None = None,
    config_path: str | None = None,
) -> tuple[DeclarationIssue, ...]:
    """The refusal of ``agent_runtime.personas.<id>.toolsets`` (ruling R2, 2026-10-08).

    The key admitted nothing since S0a A1 and ``AgentPersona.toolsets`` is gone.
    Ignoring it silently would let an operator keep editing a list that does
    nothing, so each carrier is one typed ``persona_toolsets_key_refused`` issue
    — the row ``tool-diff`` and the HUD already print. It is NOT a raise: the
    config read feeds the snapshot producer, and a raise there took the live
    serve's producer down on every rebuild (2026-10-09). ``persona_id`` narrows
    the scan to one persona."""

    issues: list[DeclarationIssue] = []
    for pid, overrides in (personas or {}).items():
        key = str(pid or "").strip()
        if not key or (persona_id is not None and key != persona_id):
            continue
        if isinstance(overrides, dict) and LEGACY_PERSONA_TOOLSETS_KEY in overrides:
            issues.append(
                DeclarationIssue(DeclarationIssueKind.LEGACY_PERSONA_TOOLSETS_KEY, _legacy_key(key), config_path)
            )
    return tuple(issues)


def _log_legacy_toolsets_key_once(persona_id: str, overrides: dict[str, Any]) -> None:
    if LEGACY_PERSONA_TOOLSETS_KEY not in overrides or persona_id in _LOGGED_LEGACY_KEYS:
        return
    _LOGGED_LEGACY_KEYS.add(persona_id)
    logger.warning(
        "persona_toolsets_key_refused key=%s value_dropped=%r",
        _legacy_key(persona_id),
        overrides.get(LEGACY_PERSONA_TOOLSETS_KEY),
    )


def skill_sources_for(stored, cfg: AgentRuntimeConfig) -> dict[str, dict[str, Any]]:
    """Which tier answered each persona's ``skills``, and what the config lost.

    S0a A6c — ACCOUNTING ONLY, no write. The persona→skill seed row asked why a
    config ``skills:`` addition does not reach a placement. The mechanism is the
    same store-wins merge as toolsets (:func:`merge_persisted_personas` merges
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

    ``stored`` is the persisted roster, passed in: this module is ``policy`` and
    never reads the store (``config.roster`` is the reader).
    """

    stored_by_id = {persona.id: persona for persona in stored}
    # A settings-only entry over a STORED persona still names the config skills the store
    # row lacks; one over no record declares nothing, so it gets no row.
    declared = _declared_ids(cfg)
    catalog = {
        persona.id: persona
        for persona in _records_from_config(cfg)
        if persona.id in stored_by_id or persona.id in declared
    }
    rows: dict[str, dict[str, Any]] = {}
    for persona_id in set(stored_by_id) | set(catalog):
        stored_row = stored_by_id.get(persona_id)
        catalog_row = catalog.get(persona_id)
        effective = list(getattr(stored_row or catalog_row, "skills", []) or [])
        declared = list(getattr(catalog_row, "skills", []) or []) if catalog_row else []
        rows[persona_id] = {
            "skills_source": "store" if stored_row is not None else "catalog",
            "catalog_only_skills": [name for name in declared if name not in effective],
        }
    return rows


def merge_persisted_personas(stored, cfg: AgentRuntimeConfig):
    """The persisted roster (``stored``, passed in) over the config-declared records — store wins."""

    catalog = {persona.id: persona for persona in persona_records_from_config(cfg)}
    merged = {**catalog, **{persona.id: persona for persona in stored}}
    return list(merged.values())


def _autonomy(persona_id: str, value: Any, current: Any) -> Any:
    """A config ``autonomy`` typed through the enum; an unknown spelling keeps ``current``."""
    from ..models import AutonomyLevel

    try:
        return AutonomyLevel(value)
    except ValueError:
        logger.warning("agent_runtime.personas.%s.autonomy %r is not an autonomy level; kept %s",
                       persona_id, value, current)
        return current


#: The settings a config-declared persona that omits them takes from THIS machine's
#: ``default_model`` / ``default_provider`` / ``default_api_mode`` (below). They are
#: the machine's, not the persona's: a realm projection of such a persona carries
#: only what its config states for them (``persona_config_sync.project_persona_definitions``).
MACHINE_DEFAULT_FIELDS = ("model", "provider", "api_mode")


def _persona_from_overrides(persona_id: str, role: str, overrides: dict[str, Any], cfg: AgentRuntimeConfig):
    from ..models import AgentPersona

    return AgentPersona(
        id=persona_id,
        display_name=str(overrides.get("display_name") or persona_id.replace("_", " ").title()),
        role=role,
        model=overrides.get("model") or cfg.default_model,
        provider=overrides.get("provider") or cfg.default_provider,
        api_mode=overrides.get("api_mode") or cfg.default_api_mode,
        system_prompt_path=str(overrides.get("system_prompt_path") or ""),
        include_core_context_files=bool(overrides.get("include_core_context_files", False)),
    )
