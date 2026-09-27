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
    """``{name, help, description}`` from a cli_commands item; None when the name is missing/invalid."""
    name = item.get("name") if isinstance(item, Mapping) else None
    if not isinstance(name, str) or not _CLI_COMMAND_NAME_RE.fullmatch(name):
        return None
    return {"name": name, "help": str(item.get("help") or ""), "description": str(item.get("description") or "")}


def parse_cli_commands(data: Mapping, key: str, manifest_list: Callable) -> list:
    """The manifest's ``cli_commands`` rows through upstream's list coercer; bad rows warn and skip."""
    return manifest_list(
        data, key, "cli_commands", "a list", cli_command_entry,
        "Plugin %s: cli_commands entry %r needs a name matching [a-z0-9][a-z0-9_-]{0,63}; skipping",
    )
