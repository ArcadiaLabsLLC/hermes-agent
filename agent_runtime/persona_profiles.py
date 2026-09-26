"""Persona <-> profile resolution that READS: the bound profile's toolset declaration
and the profile -> persona promotion.

Split out of ``agent_runtime.personas`` (lane LAYERS L4): ``personas`` keeps the
persona vocabulary (roles, aliases, blocked-tool sets, ``ToolsetDeclaration``) and
declares ``models``; the functions here read profile YAML, the roster and the
store, so they are ``stores``.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from .models import AgentPersona
from .personas import (
    _UPSTREAM_DEFAULT_TOOLSETS,
    HARNESS_LANE_DEFAULT_TOOLSETS,
    PROFILE_ROLE_SENTINEL,
    TOOLSET_SOURCE_LANE_DEFAULT,
    TOOLSET_SOURCE_PROFILE_CONFIG,
    TOOLSET_SOURCE_PROFILE_UNRESOLVED,
    AutonomyLevel,
    ToolsetDeclaration,
    profile_chat_toolsets,
    validate_toolsets,
)

__layer__ = "stores"

_LOGGER = logging.getLogger(__name__)


def _upstream_default_toolsets() -> frozenset[str]:
    try:
        from hermes_cli.config_defaults import DEFAULT_CONFIG

        values = DEFAULT_CONFIG.get("toolsets") or []
        names = frozenset(str(name).strip() for name in values if str(name or "").strip())
        return names or frozenset(_UPSTREAM_DEFAULT_TOOLSETS)
    except Exception:  # pragma: no cover - defensive; the literal is the same value
        return frozenset(_UPSTREAM_DEFAULT_TOOLSETS)


def declared_lane_toolsets(persona: AgentPersona) -> ToolsetDeclaration:
    """The harness lane's capability declaration for ``persona``.

    Resolution (R-S0a-2), from the persona's BOUND profile — not the ambient
    ``HERMES_HOME`` — so the answer does not change with the operator's active
    profile:

    * no bound/resolvable profile home ⇒ the lane default, ``profile_unresolved``
    * ``toolsets:`` absent, not a list, empty, or exactly the upstream default
      ``["hermes-cli"]`` ⇒ the lane default, ``lane_default``
    * anything else ⇒ that list verbatim, ``profile_config``

    Treating the bare ``["hermes-cli"]`` as undeclared is reading the upstream
    default as the default it is (``hermes_cli.config_defaults`` writes it for an
    unset key), not overriding an operator: any list an operator actually wrote —
    ``[harness_core, spotify]``, or a stale explicit ``[hermes-cli, …]`` — is
    honored verbatim and shows up as ``profile_config`` in ``tool-diff``.

    Never raises and never widens: a YAML fault resolves to the narrow lane
    default, the same asymmetry ``default_permission_mode`` applies to an
    unparseable permission mode.

    Cheap and registry-free: path arithmetic plus the mtime-cached YAML parse
    ``profile_readiness`` already performs, then a static ``TOOLSETS`` expansion.
    It must NEVER import ``model_tools`` — the toolset-NAME half of an agent
    create is import-free because of that (S0a A6a), and
    ``tests/agent_runtime/test_toolset_declaration.py`` asserts it in a
    subprocess.
    """

    from toolsets import expand_toolset_names

    persona_list = tuple(
        str(name).strip()
        for name in (getattr(persona, "toolsets", None) or ())
        if str(name or "").strip()
    )

    def _resolved(
        declared: tuple[str, ...],
        source: str,
        *,
        profile: str | None,
        config_path: str | None,
    ) -> ToolsetDeclaration:
        return ToolsetDeclaration(
            toolsets=tuple(validate_toolsets(expand_toolset_names(declared))),
            declared=declared,
            source=source,
            profile=profile,
            config_path=config_path,
            persona_list=persona_list,
        )

    profile_name = str(getattr(persona, "hermes_profile", "") or "").strip() or None
    try:
        from .parse_cache import cached_yaml_file
        from .profile_context import resolve_persona_profile

        binding = resolve_persona_profile(persona)
        profile_name = binding.hermes_profile or profile_name
        if binding.profile_home is None:
            return _resolved(
                HARNESS_LANE_DEFAULT_TOOLSETS,
                TOOLSET_SOURCE_PROFILE_UNRESOLVED,
                profile=profile_name,
                config_path=None,
            )
        config_path = binding.profile_home / "config.yaml"
        raw = cached_yaml_file(config_path, default={}) or {}
        value = raw.get("toolsets") if isinstance(raw, dict) else None
    except Exception:  # pragma: no cover - defensive; a declaration read must never break a turn
        _LOGGER.debug("declared_lane_toolsets: read failed for %r", getattr(persona, "id", None), exc_info=True)
        return _resolved(
            HARNESS_LANE_DEFAULT_TOOLSETS,
            TOOLSET_SOURCE_LANE_DEFAULT,
            profile=profile_name,
            config_path=None,
        )

    path_text = str(config_path)
    if not isinstance(value, list):
        return _resolved(
            HARNESS_LANE_DEFAULT_TOOLSETS,
            TOOLSET_SOURCE_LANE_DEFAULT,
            profile=profile_name,
            config_path=path_text,
        )
    names = tuple(str(name).strip() for name in value if str(name or "").strip())
    if not names or set(names) == set(_upstream_default_toolsets()):
        return _resolved(
            HARNESS_LANE_DEFAULT_TOOLSETS,
            TOOLSET_SOURCE_LANE_DEFAULT,
            profile=profile_name,
            config_path=path_text,
        )
    return _resolved(
        names,
        TOOLSET_SOURCE_PROFILE_CONFIG,
        profile=profile_name,
        config_path=path_text,
    )


def effective_toolsets(persona: AgentPersona) -> list[str]:
    """The toolsets this persona's harness lane admits by.

    ONE authority since S0a A1: the profile's declaration
    (:func:`declared_lane_toolsets`), expanded to member toolset names. Every
    existing caller — the chat chokepoint's bounded branch, the visibility
    preview, the snapshot agents drawer, the worker/dev task lanes — follows
    from here, which is what retires ``AgentPersona.toolsets`` as an admission
    input in one place rather than five.
    """

    return list(declared_lane_toolsets(persona).toolsets)


# ── profile → persona promotion ───────────────────────────────────────────────
# Re-homed here from ``agent_runtime/blueprints/resolve.py`` (mission-lane removal,
# S1). It only lived under ``blueprints/`` by accident of filing: promoting a raw
# Hermes profile into a persisted persona is a persona-lifecycle operation, not
# stage routing, and its live callers are the blueprint slot resolver *and* the
# ``POST /api/plugins/eternia-harness/profiles/{name}/promote`` endpoint, which has nothing to do
# with stage graphs. It has to outlive the blueprint package.
#
def promote_profile_to_persona(
    profile_name: str,
    *,
    slot_role: str,
    personas: dict[str, AgentPersona] | None = None,
    agent_store=None,
) -> AgentPersona:
    """Mint and persist a persona that wraps the raw Hermes profile ``profile_name``.

    A profile is only a *template* — it carries no persona record — so promotion
    persists that record and points ``hermes_profile`` at the profile. When a
    matching persisted persona exists its settings are cloned; otherwise the
    supplied role remains data and runtime defaults provide the chat settings.

    Stores are imported lazily: ``agent_runtime.config`` imports this module, so a
    top-level import would close a cycle.
    """

    from agent_runtime.store import AgentStore

    store = agent_store if agent_store is not None else AgentStore()
    known = dict(personas or {})
    explicit_single_template = (
        next(iter(personas.values())) if personas is not None and len(personas) == 1 else None
    )
    cfg = None
    if not known:
        try:
            for persona in store.list_all():
                known[persona.id] = persona
        except Exception:
            pass
        from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config

        cfg = load_agent_runtime_config()
        for persona in ensure_persisted_personas(cfg):
            known.setdefault(persona.id, persona)
    template = next(
        (
            persona
            for persona in known.values()
            if str(getattr(persona, "role", "") or "").strip() == str(slot_role or "").strip()
        ),
        None,
    ) or known.get(str(slot_role or "").strip()) or explicit_single_template
    new_id = profile_name if profile_name not in known else f"{profile_name}_{slot_role}"
    if template is not None:
        persona = replace(
            template,
            id=new_id,
            display_name=f"{profile_name} ({slot_role})",
            hermes_profile=profile_name,
            skills=list(template.skills),
            toolsets=list(template.toolsets),
            required_mcp_servers=list(template.required_mcp_servers),
            readiness={},
        )
    else:
        if cfg is None:
            from agent_runtime.config import load_agent_runtime_config

            cfg = load_agent_runtime_config()
        role = str(slot_role or "").strip() or PROFILE_ROLE_SENTINEL
        persona = AgentPersona(
            id=new_id,
            display_name=f"{profile_name} ({role})",
            role=role,
            model=cfg.default_model,
            provider=cfg.default_provider,
            api_mode=cfg.default_api_mode,
            # S66 BUGFIX: this called ``profile_chat_toolsets(profile_name)``
            # with no persona list, so ``declared`` was always ``[]`` and the
            # promoted persona was ALWAYS minted with zero toolsets — reachable
            # live through ``POST /api/plugins/eternia-harness/profiles/{name}/promote``. The declared
            # set is right here: ``known`` is the merged persona map this
            # function already built two branches up to look for a template.
            toolsets=profile_chat_toolsets(profile_name, list(known.values())),
            system_prompt_path="",
            autonomy=AutonomyLevel.PROPOSE_ONLY.value,
            hermes_profile=profile_name,
            include_profile_memory=True,
        )
    return store.save(persona)


#: The canonical spelling of the ruled ``alice_supervisor`` / ``neko_supervisor``
#: pair (:data:`_PERSONA_ID_ALIASES` owns the pair itself).
