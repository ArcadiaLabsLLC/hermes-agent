"""Fork-owned ``cli_commands`` manifest field: top-level ``hermes <name>`` commands the CLI
attaches WITHOUT importing the plugin (seam Stage 1, read by
``hermes_cli.plugins.discover_declared_cli_commands``).

Moved out of ``hermes_cli/plugins_manifest.py`` by lane FOOTPRINT-DROP (2026-09-27); the
upstream module keeps the field name, one parse call and the dataclass field. Retires
with the Stage 1 widening PR that adds the field upstream.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Mapping, Optional

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
