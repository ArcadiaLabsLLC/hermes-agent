"""Manifest-declared plugin CLI commands: ``plugin.yaml`` ``cli_commands:`` rows read WITHOUT
importing any plugin, each materialising only its own plugin when argparse sets it up.

Re-exported by :mod:`hermes_cli.plugins`; the plugin machinery is read through that module at call
time, so a test that patches ``hermes_cli.plugins.<name>`` patches what these functions see.

The file shape is PR #128648's (owner ruling 2026-10-21: the fork adopts the PR branch's shape).
Fork additions the PR does not carry: the transient load in :func:`_materialize_declared_cli_command`
and the fingerprint cache plus single readonly config read in :func:`discover_declared_cli_commands`
(``RT-HARNESS-ARGV-MANIFEST-SCAN``). The manifest field's parser stays fork-owned in
``hermes_cli/plugins_manifest_cli_commands.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from hermes_cli.plugins_manifest import PluginManifest

logger = logging.getLogger(__name__)


def cli_command_key(name: str, parent: str | None = None) -> str:
    """``PluginManager._cli_commands`` key: the argv spelling, ``"<parent> <name>"`` or ``"<name>"``."""
    return f"{parent} {name}" if parent else name


def _materialize_declared_cli_command(manifest: PluginManifest, name: str, parser: Any) -> None:
    """Stub ``setup_fn``: load ONLY ``manifest``'s plugin, run the parser setup its ``register(ctx)``
    registered for ``name``, then unload it again. Never runs ``discover_plugins``.

    The load is transient because every ``hermes`` invocation builds its parser and a later discovery
    (``gateway run``; anything importing ``model_tools``) calls ``register(ctx)`` a second time: kept
    loaded, that call hits the duplicate system-prompt-section refusal and the failed load's ledger
    sweep disposes BOTH loads. The parser keeps whatever ``setup_fn`` bound into it."""
    from hermes_cli.plugins import get_plugin_manager, manifest_key

    manager = get_plugin_manager()
    key = manifest_key(manifest)
    entry = manager._cli_commands.get(name)
    loaded_here = entry is None or entry.get("plugin_key") != key
    if loaded_here:
        manager._load_plugin(manifest)
        entry = manager._cli_commands.get(name)
    try:
        if entry is None or entry.get("plugin_key") != key:
            raise RuntimeError(f"plugin {key!r} declares CLI command {name!r} in its manifest "
                               "but register(ctx) did not register it")
        entry["setup_fn"](parser)
        if entry.get("handler_fn") is not None:
            parser.set_defaults(func=entry["handler_fn"])
    finally:
        if loaded_here:
            manager.unload(key)


def _manifest_roots() -> list[tuple[str, Path]]:
    """``(source, directory)`` in the upstream walk's scan order, read at CALL time through the same
    names ``plugins_discovery.collect_directory_manifests`` reads (tests patch them). The project
    flag is read through ``utils.env_var_enabled``, the function ``plugins._env_enabled`` aliases."""
    from hermes_cli import plugins as _plugins
    from hermes_constants import get_hermes_home
    from utils import env_var_enabled

    roots = [("bundled", Path(_plugins.get_bundled_plugins_dir())), ("user", get_hermes_home() / "plugins")]
    if env_var_enabled("HERMES_ENABLE_PROJECT_PLUGINS"):
        roots.append(("project", Path.cwd() / ".hermes" / "plugins"))
    return roots


def _declared_descriptors(manifest: PluginManifest, plugin_key: str) -> list[dict[str, Any]]:
    """The ``register_cli_command``-shaped descriptors one gated-in winner contributes."""
    commands = []
    for row in manifest.cli_commands:
        key = cli_command_key(row["name"], row["parent"])
        commands.append({
            **row, "parent": row["parent"] or None, "help": row["help"] or manifest.description or "",
            "handler_fn": None, "plugin": manifest.name, "plugin_key": plugin_key,
            "setup_fn": lambda parser, _m=manifest, _k=key: _materialize_declared_cli_command(_m, _k, parser),
        })
    return commands


def _winner_row(manifest: PluginManifest, plugin_key: str, roots: dict) -> Optional[dict]:
    """The cache row that lets a hit re-parse exactly this declaring winner, or None (uncacheable)."""
    plugin_dir, root = Path(manifest.path), roots.get(manifest.source)
    manifest_file = next((f for f in (plugin_dir / "plugin.yaml", plugin_dir / "plugin.yml") if f.exists()), None)
    if root is None or manifest_file is None:
        return None
    try:
        rel = plugin_dir.parent.relative_to(root)
    except ValueError:
        return None
    return {"manifest_path": str(manifest_file), "plugin_dir": str(plugin_dir), "source": manifest.source,
            "prefix": "" if rel == Path(".") else rel.as_posix(), "plugin_key": plugin_key}


def _cached_winners(rows) -> Optional[list]:
    """Re-parse each cached declaring winner; None (a miss) when one no longer parses to its key."""
    from hermes_cli import plugins_manifest as _pm

    winners = []
    for row in rows:
        manifest = _pm.parse_manifest_file(Path(row["manifest_path"]), Path(row["plugin_dir"]),
                                           row["source"], row["prefix"])
        if manifest is None or _pm.manifest_key(manifest) != row["plugin_key"] or not manifest.cli_commands:
            return None
        winners.append((row["plugin_key"], manifest))
    return winners


def discover_declared_cli_commands() -> list[dict[str, Any]]:
    """CLI commands declared in ``plugin.yaml`` ``cli_commands:``, found WITHOUT importing any plugin.

    One ``register_cli_command``-shaped descriptor per row, for every directory manifest discovery
    would load (same precedence and enable gate; ``HERMES_SAFE_MODE`` yields nothing). Each
    ``setup_fn`` materialises only its own plugin, so running a declared command costs one plugin
    import instead of ``discover_plugins``. Entry-point plugins have no manifest to read and
    keep the discovery path.

    ``RT-HARNESS-ARGV-MANIFEST-SCAN``: the winners come from the fingerprint cache
    (:mod:`hermes_cli.plugins_declared_cli_cache`) when no manifest file the walk could read has
    changed — a hit re-parses only the declaring manifest(s); a miss runs the full walk and rewrites
    the cache. The enable gate is never cached: it runs live on every call. A hit never changes which
    plugin wins or whether it is enabled. Pinned by ``tests/hermes_cli/test_plugin_declared_cli_commands.py``.
    """
    import time

    from hermes_cli import plugins as _plugins
    from hermes_cli import plugins_declared_cli_cache as _cache
    from hermes_constants import get_hermes_home
    from utils import env_var_enabled

    if env_var_enabled("HERMES_SAFE_MODE"):
        return []
    started = time.perf_counter()
    home, roots = get_hermes_home(), _manifest_roots()
    fingerprint = _cache.manifest_fingerprint(
        roots, env=[("HERMES_ENABLE_PROJECT_PLUGINS", str(env_var_enabled("HERMES_ENABLE_PROJECT_PLUGINS")))])
    cached = _cache.read_cache(home)
    declaring = _cached_winners(cached.rows) if cached is not None and cached.digest == fingerprint.digest() else None
    outcome = "hit"
    if declaring is None:
        winners = {_plugins.manifest_key(m): m for m in _plugins.collect_directory_manifests()}
        declaring = [(k, m) for k, m in winners.items() if m.cli_commands]
        rows = [_winner_row(m, k, dict(roots)) for k, m in declaring]
        written = None not in rows and _cache.write_cache(home, fingerprint, rows)
        outcome = "miss" if written else "unwritable"
    config = _plugins.load_config_readonly()  # one read serves both lists
    disabled, enabled = _plugins._get_disabled_plugins(config), _plugins._get_enabled_plugins(config)
    commands: list[dict[str, Any]] = []
    for plugin_key, manifest in declaring:
        if _plugins.gate_manifest(manifest, disabled, enabled).action in ("load", "load_now"):
            commands.extend(_declared_descriptors(manifest, plugin_key))
    logger.debug("declared_cli_scan cache=%s files=%d ms=%d", outcome, len(fingerprint.files),
                 int((time.perf_counter() - started) * 1000))
    return commands
