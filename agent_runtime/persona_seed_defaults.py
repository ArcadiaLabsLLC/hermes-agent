"""The ``config.yaml`` keys hermes seeds into every persona's bound profile.

Owner ruling 2026-10-03: HERMES seeds the door-fit PARTIAL keys on persona
create, not the launcher. Values: ``docs/agent-runtime-harness/planned/persona-create-seed-values-2026-10-15.md``
(approved 2026-10-15). This module is the ONE table of them and the ONE writer.

Only lines the plan settles without a further decision are in the table:

* line 1 — ``mcp_servers.<s>.env.HERMES_HOME: "${HERMES_HOME}"`` on every stdio
  server block, so a child MCP resolves the spawning persona's home (#124210 d);
* line 2 — ``credential_pool_strategies.<provider>: least_used`` for every
  provider with pooled credentials the profile can see (its own ``auth.json``,
  then the global root's, which a persona profile borrows), so selection
  spreads without an ``auth.json`` write per select (#124193).

* line 5 — ``skills.disabled`` gains every skill under the persona's search
  roots whose frontmatter is incompatible with the ``mission_chat`` surface
  (:func:`incompatible_skills`), so upstream's walkers hide what the fork's
  ``skill_view`` would refuse. Plan § "Amendment 2026-10-21", stage S5.

Line 3 is ruled out (owner 2026-10-21: creates stay profile-local and promote).
Lines 4, 6 and 8 are held in the plan's status section with the question each
still needs answered; line 7 is "leave unset" and line 9 is not a hermes key.

Rule of the writer, lines 1–2: FILL IF ABSENT. A key an operator (or an earlier seed)
already wrote is never overwritten, at any depth — a server whose ``env`` sets
``HERMES_HOME`` to anything keeps it, a provider with any strategy keeps it.
Writes go through the round-trip YAML writer one key at a time, so comments,
order and every other key survive. Fail-open per profile: a profile that will
not read or write is reported, never raised.

Rule of the writer, line 5: the sweep OWNS what it seeded and nothing else.
``seed_receipt.json`` beside ``config.yaml`` records the names it added; each
pass writes ``skills.disabled = (current − previously seeded) ∪ computed``, so an
operator's entry survives, a skill that became compatible is released, and a
name the operator already listed is never recorded as the seed's.

Two callers: :func:`agent_runtime.persona_profiles.promote_profile_to_persona`
(the fork's persona-mint door) seeds the new persona's profile at once, and
the plugin's startup sweep (:func:`seed_all_persona_profiles`) fills every
persisted persona's profile — the latter is what reaches a persona whose
profile was made by upstream's ``create_profile`` (CLI, REST or the ws
``profiles.create``), none of which the fork owns.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .machine_roots import MCP_HERMES_HOME_VALUE

__layer__ = "stores"

logger = logging.getLogger(__name__)

# Line 1's value is ``machine_roots.MCP_HERMES_HOME_VALUE`` — owned by the
# canonical MCP template's module so the seed and the readiness template cannot
# disagree (RT-MCP-TEMPLATE-VS-SEED-HERMES-HOME).
#: Line 2's value: ``agent.credential_pool.STRATEGY_LEAST_USED``.
POOL_STRATEGY_VALUE = "least_used"
#: Line 5's question: the surface and mode a persona's chat turn runs with
#: (``persona_runtime``'s ``AgentRunRequest``: ``skill_surface="mission_chat"``).
PERSONA_SKILL_SURFACE = "mission_chat"
PERSONA_ROOT_NODE_MODE = False
#: The sidecar naming what the sweep seeded, beside ``config.yaml``.
SEED_RECEIPT_NAME = "seed_receipt.json"
SEED_RECEIPT_SCHEMA_VERSION = 1
DISABLED_SKILLS_KEY = "skills.disabled"


def _escape(segment: str) -> str:
    """One dotted-path segment for ``utils.atomic_roundtrip_yaml_update``."""

    return str(segment).replace(".", "\\.")


def _read_config(path: Path) -> dict[str, Any]:
    from . import yaml_io

    if not path.is_file():
        return {}
    loaded = yaml_io.load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _pooled_providers(profile_home: Path) -> list[str]:
    """Providers with at least one pooled credential this profile can select."""

    from agent.provider_access import provider_credential_file
    from hermes_cli.harness_parts._upstream_doors import load_auth_store
    from hermes_constants import get_default_hermes_root

    names: set[str] = set()
    homes = [Path(profile_home), get_default_hermes_root()]
    for home in homes:
        pool = load_auth_store(provider_credential_file("auth.json", home)).get("credential_pool")
        if isinstance(pool, dict):
            names.update(str(name) for name, entries in pool.items() if isinstance(entries, list) and entries)
    return sorted(names)


def seed_writes(config: dict[str, Any], *, pooled_providers: Iterable[str]) -> list[tuple[str, Any]]:
    """The ``(dotted key, value)`` writes the table owes ``config`` — absent keys only."""

    writes: list[tuple[str, Any]] = []
    servers = config.get("mcp_servers")
    for name, block in sorted(servers.items()) if isinstance(servers, dict) else ():
        if not isinstance(block, dict) or not block.get("command"):
            continue  # http/sse servers run in no child process
        env = block.get("env")
        if isinstance(env, dict) and "HERMES_HOME" in env:
            continue
        if env is not None and not isinstance(env, dict):
            continue  # a malformed env is the operator's to fix, not ours to replace
        writes.append((f"mcp_servers.{_escape(name)}.env.HERMES_HOME", MCP_HERMES_HOME_VALUE))
    strategies = config.get("credential_pool_strategies")
    if strategies is None or isinstance(strategies, dict):
        present = set(strategies or {})
        for provider in pooled_providers:
            if provider not in present:
                writes.append((f"credential_pool_strategies.{_escape(provider)}", POOL_STRATEGY_VALUE))
    return writes


def incompatible_skills(profile_home: Path | str) -> frozenset[str]:
    """Names of the skills under ``profile_home``'s search roots that a persona's
    chat turn cannot load (``skill_frontmatter_runtime_compatibility`` false for
    ``mission_chat``, standard mode). ``HERMES_HOME`` is bound to the home for the
    walk, context-locally; trusted project dirs are not a property of the home
    and are left out. Upstream's ``ESSENTIAL_SKILLS`` are never named."""

    from agent.skill_utils import ESSENTIAL_SKILLS, get_skill_search_roots, iter_skill_index_files

    from .profile_context import process_home_scope
    from .skill_resolution import skill_manifest_compatibility

    names: set[str] = set()
    walked = 0
    with process_home_scope(Path(profile_home)):
        for _tier, root in get_skill_search_roots(include_project=False):
            if not Path(root).is_dir():
                continue
            for skill_md in iter_skill_index_files(Path(root), "SKILL.md"):
                walked += 1
                name, verdict = skill_manifest_compatibility(
                    skill_md, surface=PERSONA_SKILL_SURFACE, root_node_mode=PERSONA_ROOT_NODE_MODE
                )
                if not verdict.get("compatible"):
                    names.add(name)
    found = frozenset(names - ESSENTIAL_SKILLS)
    logger.info("persona_seed.line5 home=%s skills=%d incompatible=%d", profile_home, walked, len(found))
    return found


def _read_seed_receipt(home: Path) -> dict[str, Any]:
    from .serde import read_json

    path = home / SEED_RECEIPT_NAME
    if not path.is_file():
        return {}
    loaded = read_json(path)
    seeded = loaded.get("seeded") if isinstance(loaded, dict) else None
    return seeded if isinstance(seeded, dict) else {}


def disabled_skills_write(
    current: Iterable[str], previously_seeded: Iterable[str], computed: Iterable[str]
) -> tuple[list[str], list[str]]:
    """``(skills.disabled, seeded)``: ``(current − previously seeded) ∪ computed``,
    the operator's order kept, and the names the seed now owns — the computed ones
    the operator did not already list."""

    prior = set(previously_seeded)
    kept = [name for name in current if name not in prior]
    owned = sorted(set(computed) - set(kept))
    return [*kept, *owned], owned


def _seed_disabled_skills(home: Path, path: Path, config: dict[str, Any]) -> bool:
    """Line 5: rewrite ``skills.disabled`` and the receipt; ``True`` when either moved."""

    from agent.skill_utils import parse_config_string_list
    from utils import atomic_json_write, atomic_roundtrip_yaml_update

    skills = config.get("skills")
    raw = skills.get("disabled") if isinstance(skills, dict) else None
    current = parse_config_string_list(raw) if raw is not None else []
    receipt = _read_seed_receipt(home)
    previously = parse_config_string_list(receipt.get(DISABLED_SKILLS_KEY) or [])
    disabled, owned = disabled_skills_write(current, previously, incompatible_skills(home))
    moved = False
    if disabled != current and (disabled or raw is not None):
        atomic_roundtrip_yaml_update(path, DISABLED_SKILLS_KEY, disabled)
        moved = True
    if owned != sorted(previously):
        atomic_json_write(
            home / SEED_RECEIPT_NAME,
            {"schema_version": SEED_RECEIPT_SCHEMA_VERSION, "seeded": {DISABLED_SKILLS_KEY: owned}},
        )
    return moved


def seed_persona_profile(profile_home: Path | str) -> dict[str, Any]:
    """Fill the table's absent keys in ``<profile_home>/config.yaml`` (lines 1–2)
    and recompute the seed-owned part of ``skills.disabled`` (line 5)."""

    from utils import atomic_roundtrip_yaml_update

    home = Path(profile_home)
    path = home / "config.yaml"
    try:
        writes = seed_writes(_read_config(path), pooled_providers=_pooled_providers(home))
        for key, value in writes:
            atomic_roundtrip_yaml_update(path, key, value)
        if _seed_disabled_skills(home, path, _read_config(path)):
            writes.append((DISABLED_SKILLS_KEY, None))
    except Exception as exc:  # fail-open per profile: a seed must never break persona create or startup
        logger.warning("persona_seed_failed path=%s error=%s", path, type(exc).__name__, exc_info=True)
        return {"path": str(path), "seeded": [], "error": type(exc).__name__}
    for key, _value in writes:
        logger.info("persona_seed_filled path=%s key=%s", path, key)
    return {"path": str(path), "seeded": [key for key, _value in writes], "error": None}


def persona_profile_homes(personas: Iterable[Any]) -> list[Path]:
    """The distinct, existing profile homes ``personas`` are bound to."""

    from .profile_context import resolve_persona_profile

    homes: list[Path] = []
    for persona in personas:
        try:
            home = resolve_persona_profile(persona).profile_home
        except (ValueError, OSError):  # an unusable profile name or home: nothing to seed
            continue
        if home is not None and home not in homes:
            homes.append(home)
    return homes


def seed_all_persona_profiles(personas: Iterable[Any] | None = None) -> dict[str, Any]:
    """Startup sweep: seed every persisted persona's bound profile (idempotent)."""

    if personas is None:
        from .store import AgentStore

        personas = AgentStore().list_all()
    reports = [seed_persona_profile(home) for home in persona_profile_homes(personas)]
    return {
        "schema": "hermes.agent_runtime.persona_seed_defaults/v1",
        "profiles": [report for report in reports if report["seeded"] or report["error"]],
    }
