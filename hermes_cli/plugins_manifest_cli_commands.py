"""Fork-owned ``cli_commands`` manifest field: ``hermes <name>`` / ``hermes <parent> <name>``
commands the CLI attaches WITHOUT importing every plugin (seam Stage 1).

The manifest parse moved out of ``hermes_cli/plugins_manifest.py`` by lane FOOTPRINT-DROP
(2026-09-27); the declared-command scan (:func:`discover_declared_cli_commands`), its one-plugin
stub and the argv-first attach (:func:`attach_declared_cli_command`) moved out of
``hermes_cli/plugins.py`` and ``hermes_cli/main.py`` by footprint lane pb-e (2026-10-16). The
upstream modules keep one import and one call per seam. Retires with the Stage 1 widening PR
(#128648) that adds the field upstream.

Plugin-manager names are read from ``hermes_cli.plugins`` at CALL time: that module imports this
one (through ``plugins_manifest``), and tests patch its attributes.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional

if TYPE_CHECKING:
    from hermes_cli.plugins_manifest import PluginManifest

logger = logging.getLogger(__name__)

_CLI_COMMAND_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def cli_command_entry(item: object) -> Optional[Dict[str, str]]:
    """``{name, help, description, parent}`` from a cli_commands item; None when a name is invalid.

    ``parent`` names a built-in command the verb attaches under (``hermes <parent> <name>``); empty
    for a top-level ``hermes <name>``.
    """
    if not isinstance(item, Mapping):
        return None
    name, parent = item.get("name"), item.get("parent") or ""
    if not all(isinstance(v, str) and _CLI_COMMAND_NAME_RE.fullmatch(v) for v in (name, parent or "x")):
        return None
    return {"name": name, "help": str(item.get("help") or ""),
            "description": str(item.get("description") or ""), "parent": parent}


def parse_cli_commands(data: Mapping, key: str, manifest_list: Callable) -> list:
    """The manifest's ``cli_commands`` rows through upstream's list coercer; bad rows warn and skip."""
    return manifest_list(
        data, key, "cli_commands", "a list", cli_command_entry,
        "Plugin %s: cli_commands entry %r needs name (and optional parent) matching [a-z0-9][a-z0-9_-]{0,63}; skipping",
    )


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


def discover_declared_cli_commands() -> list[dict[str, Any]]:
    """CLI commands declared in ``plugin.yaml`` ``cli_commands:``, found WITHOUT importing any plugin.

    One ``register_cli_command``-shaped descriptor per row, for every directory manifest discovery
    would load (same precedence and enable gate; ``HERMES_SAFE_MODE`` yields nothing). Each
    ``setup_fn`` materialises only its own plugin, so running a declared command costs one plugin
    import instead of ``discover_plugins``. Entry-point plugins have no manifest to read and
    keep the discovery path.
    """
    from hermes_cli import plugins as _plugins
    from utils import env_var_enabled

    if env_var_enabled("HERMES_SAFE_MODE"):
        return []
    winners = {_plugins.manifest_key(m): m for m in _plugins.collect_directory_manifests()}
    config = _plugins.load_config_readonly()  # one read serves both lists
    disabled, enabled = _plugins._get_disabled_plugins(config), _plugins._get_enabled_plugins(config)
    commands: list[dict[str, Any]] = []
    for plugin_key, manifest in winners.items():
        if _plugins.gate_manifest(manifest, disabled, enabled).action not in ("load", "load_now"):
            continue
        for row in manifest.cli_commands:
            key = cli_command_key(row["name"], row["parent"])
            commands.append({
                **row, "parent": row["parent"] or None, "help": row["help"] or manifest.description or "",
                "handler_fn": None, "plugin": manifest.name, "plugin_key": plugin_key,
                "setup_fn": lambda parser, _m=manifest, _k=key: _materialize_declared_cli_command(_m, _k, parser),
            })
    return commands


def builtin_verb_subparsers(subparsers, parent: str, builtins):
    """The sub-verb action of built-in command ``parent`` (``auth`` → its ``add``/``list``/...), or None.

    ``builtins`` is ``hermes_cli.main._BUILTIN_SUBCOMMANDS``."""
    parent_parser = subparsers.choices.get(parent) if parent in builtins else None
    actions = getattr(parent_parser, "_actions", ())
    return next((a for a in actions if isinstance(a, argparse._SubParsersAction)), None)


def declared_cli_command_argv(subparsers, builtins) -> str | None:
    """The ``cli_command_key`` argv could name as a manifest-declared plugin command, else None: an
    unknown first token (``hermes <verb>``) or an unknown sub-verb of a built-in (``hermes auth
    <verb>``). Known built-in verbs return None and pay nothing."""
    from hermes_cli._parser import command_argv

    args = command_argv(sys.argv[1:])
    if not args:
        return None
    if args[0] not in builtins:
        return args[0]
    verbs = builtin_verb_subparsers(subparsers, args[0], builtins)
    if verbs is None or len(args) < 2 or args[1] in verbs.choices:
        return None
    return f"{args[0]} {args[1]}"


def attach_declared_cli_command(subparsers, builtins, attach: Callable) -> bool:
    """Attach the ``plugin.yaml``-declared command argv names, importing only its plugin.

    Found by reading manifests, never by importing plugins; the key comes from
    :func:`declared_cli_command_argv`, so it never shadows a built-in. ``attach`` is
    ``hermes_cli.main._attach_plugin_cli_command``. False when argv names no declared command or
    it failed to attach.
    """
    key = declared_cli_command_argv(subparsers, builtins)
    if key is None:
        return False
    try:
        commands = discover_declared_cli_commands()
    except Exception as exc:
        logger.warning("Declared plugin CLI scan failed: %s", exc)
        return False
    for cmd_info in commands:
        if cli_command_key(cmd_info["name"], cmd_info["parent"]) != key:
            continue
        try:
            attach(subparsers, cmd_info)
        except Exception as exc:
            logger.warning("Plugin CLI command %r failed to attach: %s", key, exc)
            return False
        return True
    return False
