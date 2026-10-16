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

Lines 3–6 and 8 are held in the plan's status section with the question each
still needs answered; line 7 is "leave unset" and line 9 is not a hermes key.

Rule of the writer: FILL IF ABSENT. A key an operator (or an earlier seed)
already wrote is never overwritten, at any depth — a server whose ``env`` sets
``HERMES_HOME`` to anything keeps it, a provider with any strategy keeps it.
Writes go through the round-trip YAML writer one key at a time, so comments,
order and every other key survive. Fail-open per profile: a profile that will
not read or write is reported, never raised.

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

__layer__ = "stores"

logger = logging.getLogger(__name__)

#: Line 1's value: interpolated by ``_load_mcp_config`` from ``os.environ``.
MCP_HERMES_HOME_VALUE = "${HERMES_HOME}"
#: Line 2's value: ``agent.credential_pool.STRATEGY_LEAST_USED``.
POOL_STRATEGY_VALUE = "least_used"


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
    from hermes_cli.auth import _load_auth_store
    from hermes_constants import get_default_hermes_root

    names: set[str] = set()
    homes = [Path(profile_home), get_default_hermes_root()]
    for home in homes:
        pool = _load_auth_store(provider_credential_file("auth.json", home)).get("credential_pool")
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


def seed_persona_profile(profile_home: Path | str) -> dict[str, Any]:
    """Fill the table's absent keys in ``<profile_home>/config.yaml``."""

    from utils import atomic_roundtrip_yaml_update

    home = Path(profile_home)
    path = home / "config.yaml"
    try:
        writes = seed_writes(_read_config(path), pooled_providers=_pooled_providers(home))
        for key, value in writes:
            atomic_roundtrip_yaml_update(path, key, value)
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
