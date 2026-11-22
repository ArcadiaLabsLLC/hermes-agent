"""On a bundled install, an agent's file tools never write a config that steers another profile.

Row RT-FU-A-BUNDLED-AGENT-CANNOT-START-A-LOCAL-MCP-SERVER-BY-WRITING-ANOTHER-PROFILES-CONFIG (review
w1118a.83). Upstream's ``tools/file_tools_write_guards.py::_check_sensitive_path`` refuses only the
ACTIVE profile's ``config.yaml``; the namespace root's and every sibling profile's stay writable, and
upstream calls its write guards "defense-in-depth, not a security boundary" because the terminal can
bypass them. On a bundled install the terminal is off, so they ARE the boundary, and one write to
another profile's config can:

* add a stdio ``mcp_servers`` entry, whose ``command`` runs at that profile's next MCP discovery with
  no approval (no ``trust:`` reads as ``full``; upstream's only gate is ``hermes mcp add``'s confirm);
* turn the install-only switches back on for every profile (``<root>/config.yaml``);
* set ``approvals.mode``, ``hooks:`` or ``plugins.enabled`` for that profile's turns.

A second shape turns this guard itself off: a ``plugins/eternia-harness/`` directory under a home
shadows the bundled harness (``hermes_cli.plugins_discovery.resolve_manifest_winners``: user beats
bundled), and a user-source copy loads only when ``plugins.enabled`` lists it, so that home's turns
run with no harness and no guard. Writes into a fork plugin's directory name under any home of the
namespace are refused for that reason.

The eternia-harness plugin's ``pre_tool_call`` hook asks :func:`namespace_config_write_refusal` for
``write_file`` and ``patch``. A path is resolved exactly as the file tools resolve it (the task's cwd,
``~``), then through ``os.path.realpath``, so ``..`` and symlinks land on the real file; an existing
target is also compared by inode to every protected config, so a hard link does not get around it.
A developer install keeps upstream's behaviour (its terminal is normally on, so the write gains
nothing there). A container or remote task writes a different filesystem and is left alone.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

__layer__ = "lanes"

__all__ = [
    "FORK_PLUGIN_PREFIX",
    "bundled_install",
    "namespace_config_write_refusal",
    "namespace_roots",
    "protected_reason",
    "write_paths",
]

#: The fork's own bundled plugins (``plugins/eternia-*``); the harness one carries this guard.
FORK_PLUGIN_PREFIX = "eternia-"
_CONFIG = "config.yaml"

logger = logging.getLogger(__name__)


def bundled_install() -> bool:
    """A phone, or a desktop whose build stamp says ``bundled`` -- the one owner of "bundled"
    (``hermes_cli.config_switches._installed_profile_config`` asks the same two)."""

    from agent_runtime.installed_profile import install_is_bundled  # the one owner of the two answers

    return install_is_bundled()


def _root_of(home: Path) -> Path:
    return home.parent.parent if home.parent.name == "profiles" else home


def namespace_roots() -> list[Path]:
    """Every namespace root this process serves: the launch root, the routed root and the active
    profile's root, as real paths (deduplicated)."""

    from hermes_constants import get_default_hermes_root, get_hermes_home, get_routing_process_hermes_home

    roots: list[Path] = []
    for read in (get_default_hermes_root, get_routing_process_hermes_home, get_hermes_home):
        try:
            root = Path(os.path.realpath(_root_of(Path(read()))))
        except (OSError, ValueError):
            continue
        if root not in roots:
            roots.append(root)
    return roots


def _fold(part: str) -> str:
    return part.casefold()  # a case-insensitive filesystem (Windows, macOS) opens Config.YAML too


def _lexical_reason(real: Path, root: Path) -> str | None:
    try:
        parts = tuple(_fold(p) for p in real.relative_to(root).parts)
    except ValueError:
        return None
    if parts == (_CONFIG,):
        return "the namespace root's config.yaml, which every profile of this install reads"
    if len(parts) == 3 and parts[0] == "profiles" and parts[2] == _CONFIG:
        return f"profile {real.parent.name}'s config.yaml"
    home_rest = parts[1:] if parts[:1] == ("plugins",) else (
        parts[3:] if len(parts) > 3 and parts[0] == "profiles" and parts[2] == "plugins" else ())
    if home_rest and home_rest[0].startswith(FORK_PLUGIN_PREFIX):
        return (f"a copy of the bundled {real.relative_to(root).parts[-len(home_rest)]} plugin, which would "
                "shadow the bundled one and switch its safety checks off")
    return None


def _protected_configs(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        found.append(root / _CONFIG)
        try:
            found.extend(sorted((root / "profiles").glob(f"*/{_CONFIG}")))
        except OSError:
            continue
    return found


def _same_inode(real: Path, configs: Iterable[Path]) -> Path | None:
    try:
        target = os.stat(real)
    except OSError:
        return None
    for config in configs:
        try:
            if os.path.samestat(target, os.stat(config)):
                return config
        except OSError:
            continue
    return None


def protected_reason(path: Path | str, roots: Iterable[Path]) -> str | None:
    """Why writing *path* (already anchored to the task's cwd) is refused, else None."""

    real = Path(os.path.realpath(path))
    roots = list(roots)
    for root in roots:
        reason = _lexical_reason(real, root)
        if reason is not None:
            return reason
    linked = _same_inode(real, _protected_configs(roots))
    if linked is not None:
        return f"a link to {linked.name} of {linked.parent}"
    return None


def write_paths(tool_name: str, args: dict) -> list[str]:
    """Every path a ``write_file`` / ``patch`` call writes, as ``tools/file_tools.py`` collects them:
    ``path``, plus each V4A header's (a Move's both ends) in ``patch`` mode. A V4A body that does not
    parse adds none; upstream refuses to apply it."""

    paths: list[Any] = [args.get("path")]
    if tool_name == "patch" and (args.get("mode") or "replace") == "patch":
        from tools.patch_parser import parse_v4a_patch

        operations, error = parse_v4a_patch(str(args.get("patch") or ""))
        if not error:
            paths += [p for op in operations for p in (op.file_path, op.new_path)]
    return [p for p in paths if isinstance(p, str) and p.strip()]


def _host_path(filepath: str, task_id: str) -> Path | None:
    """The host path the file tool writes, or None for a container or remote task."""

    from agent_runtime._upstream_doors import file_tool_path_for_task

    try:
        resolved = file_tool_path_for_task(filepath, task_id or "default")
    except (OSError, ValueError):
        return Path(os.path.abspath(os.path.expanduser(filepath)))
    return resolved if isinstance(resolved, Path) else None


def namespace_config_write_refusal(tool_name: Any, args: Any, task_id: str = "", *,
                                   bundled: Callable[[], bool] | None = None,
                                   roots: Callable[[], list[Path]] | None = None) -> dict | None:
    """``pre_tool_call``: a ``write_file`` / ``patch`` on a bundled install that names the namespace
    root's or any profile's ``config.yaml`` (or a fork plugin's directory under a home) is blocked;
    else None."""

    if tool_name not in ("write_file", "patch") or not isinstance(args, dict):
        return None
    paths = write_paths(tool_name, args)
    if not paths or not (bundled or bundled_install)():
        return None
    roots = roots or namespace_roots
    for filepath in paths:
        try:  # a hook that raises lets the call through (upstream fails open), so this fails closed
            host = _host_path(filepath.strip(), task_id)
            reason = None if host is None else protected_reason(host, roots())
        except Exception:  # health: allow BLE001 -- the boundary refuses what it cannot check
            logger.warning("namespace config guard: could not check %r; refused", filepath, exc_info=True)
            reason = "a path whose target could not be checked"
        if reason is not None:
            return {"action": "block", "message": (
                f"Refusing to write {filepath}: it is {reason}. An agent on this install cannot change "
                "the settings, MCP servers, hooks or plugins of the install or of another agent; "
                "nothing was written. Ask the person to change it in Eternia's settings.")}
    return None
