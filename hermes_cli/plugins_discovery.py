"""Plugin discovery: directory scanning, entry-point manifests, and the enable/disable gate.

Split out of :mod:`hermes_cli.plugins`. Names that tests patch on the origin
(``get_bundled_plugins_dir``, ``_env_enabled``) are looked up lazily through it.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, Set, Tuple

from hermes_constants import get_hermes_home
from hermes_cli.config import cfg_get
from hermes_cli.plugin_capabilities import VALID_CAPABILITY_IDS
from hermes_cli.plugin_capabilities import parse_declared_capabilities as _parse_declared_capabilities
from hermes_cli.plugins_manifest import (
    PluginManifest, _detect_kind_from_source, manifest_key, _resolve_module_source,
    parse_manifest_file, portable_plugin_manifest,
)
from hermes_cli.relay_plugin_cutover import LEGACY_RELAY_PLUGIN_KEYS, RELAY_PLUGINS_CONFIG_ENV

logger = logging.getLogger("hermes_cli.plugins")

ENTRY_POINTS_GROUP = "hermes_agent.plugins"
ENTRY_POINT_CAPABILITIES_GROUP = "hermes_agent.plugin_capabilities"


def _select_entry_point_group(entry_points: Any, group: str) -> list:
    """Return one metadata entry-point group across supported Python APIs."""
    if hasattr(entry_points, "select"):
        return list(entry_points.select(group=group))
    if isinstance(entry_points, dict):
        return list(entry_points.get(group, []))
    return [ep for ep in entry_points if ep.group == group]


def discover_entrypoint_manifests() -> List["PluginManifest"]:
    """Return metadata-only manifests for installed entry-point plugins. Kind comes from an import-free source
    scan (memory/model providers route to their own discovery). Capabilities come from the companion
    ``hermes_agent.plugin_capabilities`` group (``<plugin-id>.<capability-id>`` entries pointing at the same
    object), so consent works without importing plugin code. Failures are isolated per entry point."""
    manifests: List[PluginManifest] = []
    try:
        eps = importlib.metadata.entry_points()
        group_eps = _select_entry_point_group(eps, ENTRY_POINTS_GROUP)
        capability_eps = _select_entry_point_group(eps, ENTRY_POINT_CAPABILITIES_GROUP)
    except Exception as exc:
        logger.debug("Entry-point scan failed: %s", exc)
        return manifests
    for ep in group_eps:
        try:
            declared = {d.name for d in capability_eps if d.value == ep.value}
            capabilities = [c for c in VALID_CAPABILITY_IDS if f"{ep.name}.{c}" in declared]
            dist = getattr(ep, "dist", None)
            metadata = getattr(dist, "metadata", None)
            manifests.append(PluginManifest(
                name=ep.name, version=str(getattr(dist, "version", "") or ""),
                description=str(metadata.get("Summary", "") or "") if metadata is not None else "",
                source="entrypoint", path=ep.value, key=ep.name,
                kind=_classify_entrypoint_value_kind(ep.value),
                capabilities=_parse_declared_capabilities(capabilities, ep.name),
            ))
        except Exception as exc:
            logger.debug("Entry-point manifest for %r skipped: %s", getattr(ep, "name", "?"), exc)
    return manifests


def _classify_entrypoint_value_kind(value: str) -> str:
    """Classify an entry-point target by import-free source scan (unresolvable -> standalone)."""
    try:
        module_name = str(value).split(":", 1)[0].strip()
        return (_detect_kind_from_source(_resolve_module_source(module_name)) if module_name else None) or "standalone"
    except Exception:
        return "standalone"


def _get_disabled_plugins(config: Optional[Any] = None) -> set:
    """Read ``plugins.disabled`` — a deny-list that wins over ``plugins.enabled``."""
    try:
        from hermes_cli.config import load_config_readonly
        disabled = cfg_get(load_config_readonly() if config is None else config, "plugins", "disabled", default=[])
        return set(disabled) if isinstance(disabled, list) else set()
    except Exception:
        return set()


def _get_enabled_plugins(config: Optional[Any] = None) -> Optional[set]:
    """Read the ``plugins.enabled`` allow-list (plugins are opt-in). ``None`` = key missing/malformed ("nothing
    enabled yet"; the first ``migrate_config`` run grandfathers installed user plugins); ``set()`` = explicitly
    empty; else the allow-list."""
    try:
        from hermes_cli.config import load_config_readonly
        enabled = cfg_get(load_config_readonly() if config is None else config, "plugins", "enabled")
        return set(enabled) if isinstance(enabled, list) else None
    except Exception:
        return None


def iter_manifest_candidates(
    path: Path, *, skip_names: Optional[Set[str]] = None, prefix: str = "", depth: int = 0
) -> Iterator[Tuple[Path, Optional[Path], bool, str]]:
    """Walk *path* the way :func:`scan_directory` does, reading no manifest: yields ``(plugin_dir,
    yaml_manifest_or_None, has_portable_json, prefix)`` for every directory that holds a manifest —
    flat ``<root>/<name>/plugin.yaml`` or category ``<root>/<cat>/<name>/plugin.yaml`` (a
    manifest-less directory recurses one level, depth capped at two)."""
    if not path.is_dir():
        return
    for child in sorted(path.iterdir()):
        try:
            if not child.is_dir() or (depth == 0 and skip_names and child.name in skip_names):
                continue
            manifest_file = next((f for f in (child / "plugin.yaml", child / "plugin.yml") if f.exists()), None)
            portable_file = child / "plugin.json"
            has_portable = portable_file.exists() or portable_file.is_symlink()
        except OSError as exc:
            # stat() raises (not "False") on an unsearchable directory — Windows ACLs (WinError 5) or a
            # mode-000 dir; one such plugin must not abort discovery for every other plugin (#111804).
            logger.warning("Skipping unreadable plugin directory %s: %s", child, exc)
            continue
        if manifest_file is not None or has_portable:
            yield child, manifest_file, has_portable, prefix
        elif depth >= 1:
            logger.debug("Skipping %s (no plugin.yaml, depth cap reached)", child)
        else:
            sub_prefix = f"{prefix}/{child.name}" if prefix else child.name
            yield from iter_manifest_candidates(child, prefix=sub_prefix, depth=depth + 1)


def scan_directory(
    path: Path, source: str, *, skip_names: Optional[Set[str]] = None, prefix: str = "", depth: int = 0
) -> List[PluginManifest]:
    """Read manifests under *path*: flat ``<root>/<name>/plugin.yaml`` (key ``name``) or category
    ``<root>/<cat>/<name>/plugin.yaml`` (key ``cat/name``; a manifest-less directory recurses one level, depth
    capped at two). *skip_names* ignores top-level names; portable ``plugin.json`` packages are accepted
    alongside YAML manifests."""
    manifests: List[PluginManifest] = []
    for child, manifest_file, _has_portable, child_prefix in iter_manifest_candidates(
            path, skip_names=skip_names, prefix=prefix, depth=depth):
        manifest = _parse_candidate(child, manifest_file, source, child_prefix)
        if manifest is not None:
            manifests.append(manifest)
    return manifests


def _parse_candidate(
    child: Path, manifest_file: Optional[Path], source: str, prefix: str
) -> Optional[PluginManifest]:
    """Parse one candidate from :func:`iter_manifest_candidates` (YAML wins over ``plugin.json``)."""
    if manifest_file is not None:
        return parse_manifest_file(manifest_file, child, source, prefix)
    try:
        return portable_plugin_manifest(child, source, prefix)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", child / "plugin.json", exc)
        return None


def manifest_roots() -> List[Tuple[str, Path, str, Optional[Set[str]]]]:
    """``(label, directory, source, skip_names)`` in full-discovery order: bundled top-level (its
    self-discovering categories skipped), bundled/platforms, user, opt-in project."""
    from hermes_cli import plugins as _origin  # patched names resolve through the origin
    repo_plugins = _origin.get_bundled_plugins_dir()
    roots: List[Tuple[str, Path, str, Optional[Set[str]]]] = [
        ("bundled (top-level)", repo_plugins, "bundled", {"memory", "context_engine", "platforms", "model-providers"}),
        ("bundled/platforms", repo_plugins / "platforms", "bundled", None),
        ("user", get_hermes_home() / "plugins", "user", None),
    ]
    if _origin._env_enabled("HERMES_ENABLE_PROJECT_PLUGINS"):
        roots.append(("project", Path.cwd() / ".hermes" / "plugins", "project", None))
    else:
        logger.debug("Project plugins disabled (set HERMES_ENABLE_PROJECT_PLUGINS=1 to enable)")
    return roots


def collect_directory_manifests() -> List[PluginManifest]:
    """Read directory manifests in full-discovery order (bundled top-level, bundled/platforms, user, opt-in
    project) without loading or mutating anything, so startup probes share the exact precedence/containment
    rules of the real discovery sweep."""
    manifests: List[PluginManifest] = []
    for label, directory, source, skip_names in manifest_roots():
        found = scan_directory(directory, source, skip_names=skip_names)
        logger.debug("  %s: %d manifest(s) in %s", label, len(found), directory)
        manifests.extend(found)
    return manifests


def collect_declared_cli_manifests() -> List[PluginManifest]:
    """The WINNING directory manifests that declare ``cli_commands``, parsing only what that needs.

    Same walk and precedence as :func:`collect_directory_manifests`, but each manifest is read as text
    first: only files mentioning ``cli_commands`` are parsed, plus any manifest that could share a
    declaring manifest's key (a path-derived key equal to it, or a name-derived key whose directory name
    or manifest text contains it). Nothing else is parsed, so a startup that only needs the declared
    commands does not YAML-parse every installed plugin. The text test over-approximates in the safe
    direction: it can only cause an extra parse, never a skipped override.
    """
    candidates = []
    for _label, directory, source, skip_names in manifest_roots():
        for child, manifest_file, _has_portable, prefix in iter_manifest_candidates(
                directory, skip_names=skip_names):
            text_file = manifest_file if manifest_file is not None else child / "plugin.json"
            try:
                text = text_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""  # unreadable: the parse reports it if it is ever needed
            candidates.append((child, manifest_file, source, prefix, text))
    parsed: dict = {}

    def _parse(index: int) -> Optional[PluginManifest]:
        if index not in parsed:
            child, manifest_file, source, prefix, _text = candidates[index]
            parsed[index] = _parse_candidate(child, manifest_file, source, prefix)
        return parsed[index]

    keys = set()
    for index, (_child, manifest_file, _source, _prefix, text) in enumerate(candidates):
        if manifest_file is not None and "cli_commands" in text:
            manifest = _parse(index)
            if manifest is not None and manifest.cli_commands:
                keys.add(manifest_key(manifest))
    if not keys:
        return []

    def _may_share_a_key(child: Path, prefix: str, text: str) -> bool:
        if prefix:
            return f"{prefix}/{child.name}" in keys
        return child.name in keys or any(key in text for key in keys)

    winners = {}
    for index, (child, _manifest_file, _source, prefix, text) in enumerate(candidates):
        if index in parsed or _may_share_a_key(child, prefix, text):
            manifest = _parse(index)
            if manifest is not None:
                winners[manifest_key(manifest)] = manifest
    return [m for key, m in winners.items() if key in keys and m.cli_commands]


@dataclass(frozen=True)
class ManifestGate:
    """Routing verdict for one winning manifest (see :func:`gate_manifest`)."""

    action: str  # "load" (dependency-ordered pass) | "placeholder" | "load_now" | "defer"
    enabled: bool = False
    error: Optional[str] = None
    log: Optional[tuple] = None  # (level, message, *args)


def gate_manifest(
    manifest: PluginManifest, disabled: Set[str], enabled: Optional[Set[str]]
) -> ManifestGate:
    """Decide how one winning manifest is handled. Gate order matters: legacy relay refusal, explicit disable,
    category-owned kinds (exclusive / model-provider), bundled auto-loads (backend now, platform deferred),
    then ``plugins.enabled`` opt-in (path-derived key or legacy bare name)."""
    lookup_key = manifest_key(manifest)
    names = {lookup_key, manifest.name}

    def _placeholder(error: Optional[str], level: int, message: str, *args, enabled: bool = False) -> ManifestGate:
        return ManifestGate("placeholder", enabled=enabled, error=error, log=(level, message, lookup_key, *args))

    # Relay lifecycle is core-owned; an old plugin copy would compete for its registries.
    if names & LEGACY_RELAY_PLUGIN_KEYS:
        error = (
            "removed — Relay lifecycle is owned by Hermes core; configure "
            f"{RELAY_PLUGINS_CONFIG_ENV} instead"
        )
        return _placeholder(error, logging.WARNING, "Refusing to load removed Hermes Relay plugin '%s'; %s", error)
    if names & disabled:
        return _placeholder("disabled via config", logging.DEBUG, "Skipping disabled plugin '%s'")
    # Exclusive plugins (memory providers) have their own activation path; record only.
    if manifest.kind == "exclusive":
        return _placeholder(
            "exclusive plugin — activate via <category>.provider config", logging.DEBUG,
            "Skipping '%s' (exclusive, handled by category discovery)",
        )
    # Model providers load via providers/__init__.py; a second import here would create two ProviderProfile
    # instances and break the bundled-vs-user "last writer wins" override.
    if manifest.kind == "model-provider":
        return _placeholder(
            None, logging.DEBUG, "Skipping '%s' (model-provider, handled by providers/ discovery)", enabled=True)
    if manifest.source == "bundled":
        # Bundled backends auto-load; selection among them is ``<category>.provider`` config.
        if manifest.kind == "backend":
            return ManifestGate("load_now")
        # Bundled platforms register LAZILY: eagerly importing ~20 heavy SDKs added seconds to every `hermes`
        # invocation. A deferred loader keeps every platform available on first use.
        if manifest.kind == "platform":
            return ManifestGate("defer")
    if enabled is None or not names & enabled:
        return _placeholder(
            f"not enabled in config (run `hermes plugins enable {lookup_key}` to activate)", logging.DEBUG,
            "Skipping '%s' (not in plugins.enabled)",
        )
    return ManifestGate("load")
