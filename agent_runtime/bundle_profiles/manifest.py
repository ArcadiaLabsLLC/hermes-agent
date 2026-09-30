"""A bundle profile manifest: which toolsets and features one Hermes distribution switches off.

One fork-owned YAML file per profile (``<profile>.yaml`` beside this module).
The manifest adds no switch of its own — every entry is applied through a
switch Hermes already has:

* ``toolsets.disabled`` -> config ``agent.disabled_toolsets``, which
  ``model_tools._select_tool_names`` subtracts LAST from every selection;
* ``config`` -> existing config keys (validated against
  ``hermes_cli.config_defaults.DEFAULT_CONFIG`` plus the few keys read with an
  in-code default, named in :data:`KEYS_READ_OUTSIDE_DEFAULTS`);
* ``environment`` -> variables an existing dependency already honours;
* ``refused_routes`` -> upstream routes refused caller-side
  (:mod:`agent_runtime.bundle_profiles.route_gate`);
* ``packaging`` -> the import-closure walk's roots and switched-off modules,
  the optional extras the bundle ships, and the base distributions it omits
  (``scripts/bundle_profile_closure.py``); for a phone profile also its targets,
  the skill marker, and the compiled distributions it admits
  (``scripts/bundle_profile_gate.py``).

``unswitched`` records the matrix rows that have no existing switch, so the gap
is data a reader can see rather than a flag somebody invented.
"""

from __future__ import annotations

import copy
import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agent_runtime import yaml_io

__layer__ = "policy"

PROFILES_DIR = Path(__file__).resolve().parent
SCHEMA_VERSION = 1

#: Config keys Hermes reads with an in-code default and no DEFAULT_CONFIG entry.
#: Each names its reader, so the exception is checkable. The distribution switches
#: (default on = today's behaviour) are read through ``hermes_cli.config.config_switch``
#: and live here rather than in upstream's DEFAULT_CONFIG, so the fork adds no lines
#: to that file.
KEYS_READ_OUTSIDE_DEFAULTS = {
    "delegation.worktree_isolation": "tools/delegate_tool_config.py::_get_worktree_isolation",
    "mcp.stdio_servers": "tools/mcp_tool_common.py::mcp_stdio_servers_allowed",
    "mcp.client": "tools/mcp_tool_common.py::mcp_client_enabled",
    "tts.piper.download_voices": "tools/tts_tool_local.py::_load_piper_voice_for_config",
    "terminal.external_backends": "tools/terminal_tool_backends.py::external_backends_allowed",
    "gateway.platform_adapters": "gateway/run_adapters.py::platform_adapters_allowed",
    "updates.checkout_bound": "agent_runtime/build_stamp.py::checkout_bound_enabled",
    "voice.mode_enabled": "tui_gateway/methods_voice.py::_voice_mode_available",
    # The phone switches (embedded-hermes plan Stage 2 steps 6 and 8, and the sign-in runner).
    "agent.provider_sdks": "agent/transports/httpx_client.py::provider_sdks_enabled",
    "conversations.subprocess_worker": "agent_runtime/conversations/worker.py::subprocess_worker_enabled",
    "auth.subprocess_signin": "agent_runtime/provider_signin.py::subprocess_signin_enabled",
    "tui_gateway.pydantic_contracts": "tui_gateway/contract_seam.py::pydantic_contracts_enabled",
    "sessions.git_probe": "tui_gateway/git_probe.py::git_probe_enabled",
    # Upstream's own connectors switch (read with an in-code default, no DEFAULT_CONFIG entry).
    "tools.connectors.enabled": "tools/connectors/gateway/config.py::load_config",
    # ``providers.<slug>.enabled`` is upstream's per-provider switch (DEFAULT_CONFIG's ``providers``
    # is an empty mapping, so no slug is a default key).
    "providers.qwen-oauth.enabled": "hermes_cli/config_providers.py::is_provider_enabled",
    # The Launcher is the one model downloader (embedded-hermes plan D1-D3): default on = full Hermes.
    "local_models.downloads": "agent_runtime/bundle_profiles/model_downloads.py::model_downloads_enabled",
    # Default OFF: sign-ins in the OS secure store (owner ruling 2026-09-28 item 4).
    "auth.os_secure_store": "agent_runtime/host_store/desktop_binding.py::os_secure_store_enabled",
}


class ProfileManifestError(ValueError):
    """The manifest names something Hermes does not have, or is malformed."""


@dataclass(frozen=True)
class RefusedRoutes:
    feature: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class ProfileManifest:
    profile: str
    disabled_toolsets: tuple[str, ...]
    config: Mapping[str, Any]
    environment: Mapping[str, str]
    refused_routes: RefusedRoutes
    unswitched: tuple[Mapping[str, str], ...]
    packaging_roots: tuple[str, ...]
    switched_off_modules: tuple[str, ...]
    packaging_extras: tuple[str, ...] = ()
    omitted_distributions: tuple[Mapping[str, Any], ...] = ()
    # The packaging step (scripts/bundle_profile_package.py).
    #: agent resources shipped beside the code: a ``scripts/build/inputs.py`` RESOURCE_ENV name
    #: (``skills``) or a repo-relative directory (the harness skills); ``--verify`` checks each ships
    packaging_resources: tuple[str, ...] = ()
    #: bundled plugin directories (``plugins/<dir>``) that ship; an unlisted one is not packaged
    packaging_plugins: tuple[str, ...] = ()
    #: bundle-root-relative path or glob (``app/...``, ``site-packages/...``) -> why it is left out
    excluded_data: Mapping[str, str] = dataclasses.field(default_factory=dict)
    #: engine pack name -> the extras it carries OUTSIDE the core bundle (downloaded on first use)
    packaging_packs: Mapping[str, tuple[str, ...]] = dataclasses.field(default_factory=dict)
    #: base distribution -> how it is reached with no static import (stdlib ``zoneinfo`` loads
    #: ``tzdata``); the closure ships it, and refuses a name that is not a base dependency
    dynamic_distributions: Mapping[str, str] = dataclasses.field(default_factory=dict)
    #: requirement of a shipped distribution -> why a placeholder module stands in for it
    #: (``av`` under faster-whisper: arrays only); the closure never follows into it
    placeholder_distributions: Mapping[str, str] = dataclasses.field(default_factory=dict)
    #: ``scripts/bundle_profile_closure.TARGETS`` keys the bundle is built for; empty = the
    #: desktop installer's interpreter
    packaging_targets: tuple[str, ...] = ()
    #: when non-empty, a skill ships only if its ``platforms:`` frontmatter names one of these —
    #: the existing per-skill OS switch, so a phone ships only skills marked for phones
    packaging_skill_platforms: tuple[str, ...] = ()
    #: compiled (non-pure-Python) distribution -> why the profile gate admits it
    admitted_native: Mapping[str, str] = dataclasses.field(default_factory=dict)
    #: ship the forced set's scanned-package modules under the sibling root the embedded entry mounts
    #: (``agent_runtime/bundle_profiles/forced_tree.py``), never under the scanned ``tools/`` / ``plugins/``
    packaging_forced_sibling_tree: bool = False


def manifest_path(profile: str) -> Path:
    return PROFILES_DIR / f"{profile}.yaml"


def load_profile(profile: str, *, validate: bool = True) -> ProfileManifest:
    """Read ``<profile>.yaml``; with ``validate`` every name is checked against Hermes."""
    path = manifest_path(profile)
    if not path.is_file():
        raise ProfileManifestError(f"no bundle profile manifest at {path}")
    return parse_manifest(yaml_io.load(path.read_text(encoding="utf-8")), validate=validate)


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ProfileManifestError(f"{where} must be a list of non-empty strings")
    return tuple(value)


def _mapping(value: Any, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProfileManifestError(f"{where} must be a mapping")
    return dict(value)


def _omitted(row: Any) -> dict:
    row = _mapping(row, "packaging.omitted_distributions[]")
    name, degrades = row.get("distribution"), row.get("degrades")
    if not isinstance(name, str) or not name or not isinstance(degrades, str) or not degrades:
        raise ProfileManifestError("packaging.omitted_distributions[] needs a distribution and what it degrades")
    imports = _strings(row.get("imports"), "packaging.omitted_distributions[].imports")
    if not imports:
        raise ProfileManifestError(f"omitted distribution {name!r} must name its import names")
    stand_in = row.get("stand_in")
    if stand_in is not None and (not isinstance(stand_in, str) or not stand_in):
        raise ProfileManifestError(f"omitted distribution {name!r}: stand_in names a module")
    dropped = _strings(row.get("dropped_extras"), "packaging.omitted_distributions[].dropped_extras")
    if any(not re.fullmatch(r"[A-Za-z0-9._-]+\[[A-Za-z0-9._-]+\]", entry) for entry in dropped):
        raise ProfileManifestError(f"omitted distribution {name!r}: dropped_extras entries are 'dist[extra]'")
    out = {"distribution": name, "imports": imports, "degrades": degrades}
    if dropped:
        # A shipped distribution's requested extra that requires this one ships WITHOUT that extra; the
        # closure proves the distribution still imports with this one absent (bundle_profile_closure).
        out["dropped_extras"] = dropped
    if stand_in:
        out["stand_in"] = stand_in  # a first-party module whose stand_in_modules() the entry registers
    return out


def _flag(value: Any, where: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ProfileManifestError(f"{where} must be true or false")
    return value


def _reasons(value: Any, where: str) -> dict[str, str]:
    """A path -> non-empty reason mapping: every entry says why it exists."""
    value = _mapping(value, where)
    if not all(isinstance(k, str) and k and isinstance(v, str) and v.strip() for k, v in value.items()):
        raise ProfileManifestError(f"{where} must map names to non-empty reasons")
    return value


def parse_manifest(data: Any, *, validate: bool = True) -> ProfileManifest:
    """Build a :class:`ProfileManifest` from parsed YAML."""
    data = _mapping(data, "manifest")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ProfileManifestError(f"schema_version must be {SCHEMA_VERSION}")
    profile = data.get("profile")
    if not isinstance(profile, str) or not profile:
        raise ProfileManifestError("profile must be a non-empty string")
    routes = _mapping(data.get("refused_routes"), "refused_routes")
    packaging = _mapping(data.get("packaging"), "packaging")
    environment = _mapping(data.get("environment"), "environment")
    if not all(isinstance(v, str) for v in environment.values()):
        raise ProfileManifestError("environment values must be strings")
    manifest = ProfileManifest(
        profile=profile,
        disabled_toolsets=_strings(_mapping(data.get("toolsets"), "toolsets").get("disabled"), "toolsets.disabled"),
        config=_mapping(data.get("config"), "config"),
        environment=environment,
        refused_routes=RefusedRoutes(
            feature=str(routes.get("feature") or ""),
            paths=_strings(routes.get("paths"), "refused_routes.paths"),
        ),
        unswitched=tuple(_mapping(row, "unswitched[]") for row in (data.get("unswitched") or [])),
        packaging_roots=_strings(packaging.get("roots"), "packaging.roots"),
        switched_off_modules=_strings(packaging.get("switched_off_modules"), "packaging.switched_off_modules"),
        packaging_extras=_strings(packaging.get("extras"), "packaging.extras"),
        omitted_distributions=tuple(_omitted(row) for row in (packaging.get("omitted_distributions") or [])),
        packaging_resources=_strings(packaging.get("resources"), "packaging.resources"),
        packaging_plugins=_strings(packaging.get("plugins"), "packaging.plugins"),
        excluded_data=_reasons(packaging.get("excluded_data"), "packaging.excluded_data"),
        packaging_packs={name: _strings(_mapping(pack, f"packaging.packs.{name}").get("extras"),
                                        f"packaging.packs.{name}.extras")
                         for name, pack in _mapping(packaging.get("packs"), "packaging.packs").items()},
        dynamic_distributions=_reasons(packaging.get("dynamic_distributions"), "packaging.dynamic_distributions"),
        placeholder_distributions=_reasons(packaging.get("placeholder_distributions"),
                                           "packaging.placeholder_distributions"),
        packaging_targets=_strings(packaging.get("targets"), "packaging.targets"),
        packaging_skill_platforms=_strings(packaging.get("skill_platforms"), "packaging.skill_platforms"),
        admitted_native=_reasons(packaging.get("admitted_native"), "packaging.admitted_native"),
        packaging_forced_sibling_tree=_flag(packaging.get("forced_sibling_tree"), "packaging.forced_sibling_tree"),
    )
    if validate:
        validate_manifest(manifest)
    return manifest


def known_toolset_names() -> set[str]:
    """Static toolsets plus every toolset a builtin registers into (no registrar import)."""
    from agent_runtime.harness_toolset import ensure_harness_core
    from toolsets import TOOLSETS
    from tools.toolset_manifest import builtin_toolset_names

    ensure_harness_core()

    return set(TOOLSETS) | set(builtin_toolset_names())


def _default_has(dotted: str) -> bool:
    from hermes_cli.config_defaults import DEFAULT_CONFIG

    node: Any = DEFAULT_CONFIG
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def validate_manifest(manifest: ProfileManifest) -> None:
    """Fail loud on a toolset or config key Hermes does not have — no invented switches."""
    unknown = sorted(set(manifest.disabled_toolsets) - known_toolset_names())
    if unknown:
        raise ProfileManifestError(f"unknown toolsets in toolsets.disabled: {unknown}")
    bad_keys = sorted(
        key for key in manifest.config
        if "." not in key or not (_default_has(key) or key in KEYS_READ_OUTSIDE_DEFAULTS)
    )
    if bad_keys:
        raise ProfileManifestError(f"config keys Hermes does not read: {bad_keys}")
    if manifest.refused_routes.paths and not manifest.refused_routes.feature:
        raise ProfileManifestError("refused_routes.feature must name the switched-off feature")


def apply_to_config(manifest: ProfileManifest, config: Mapping[str, Any]) -> dict:
    """Return a copy of ``config`` with the profile's switches applied.

    ``agent.disabled_toolsets`` becomes the union of what the config already
    disables and what the profile disables (order kept, config first); each
    ``config`` entry overwrites its dotted key.
    """
    result = copy.deepcopy(dict(config))
    agent = result.setdefault("agent", {})
    if not isinstance(agent, dict):
        raise ProfileManifestError("config.agent must be a mapping")
    existing = agent.get("disabled_toolsets") or []
    if isinstance(existing, str):
        existing = [existing]
    merged = list(dict.fromkeys([*existing, *manifest.disabled_toolsets]))
    agent["disabled_toolsets"] = merged
    for dotted, value in manifest.config.items():
        *parents, leaf = dotted.split(".")
        node = result
        for part in parents:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ProfileManifestError(f"config key {dotted!r} crosses a non-mapping at {part!r}")
            node = child
        node[leaf] = copy.deepcopy(value)
    return result


def process_environment(manifest: ProfileManifest, base: Mapping[str, str]) -> dict[str, str]:
    """``base`` plus the profile's environment (the profile wins)."""
    return {**dict(base), **dict(manifest.environment)}
