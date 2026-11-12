"""Fork-owned ``cli_commands`` manifest field: ``hermes <name>`` / ``hermes <parent> <name>``
commands the CLI attaches WITHOUT importing every plugin (seam Stage 1).

The manifest parse moved out of ``hermes_cli/plugins_manifest.py`` by lane FOOTPRINT-DROP
(2026-09-27); ``hermes_cli/plugins_manifest.py`` keeps one import and one call. The declared-command
scan lives in ``hermes_cli/plugins_declared_cli.py`` and the argv-first attach in
``hermes_cli/main_plugin_cli.py``, the file shape of PR #128648 (owner ruling 2026-10-21). Retires
with that PR, which adds the field upstream.
"""

from __future__ import annotations

import re
from typing import Callable, Mapping, Optional

_CLI_COMMAND_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# ``setup: "<dotted module>:<function>"`` — the parser setup the CLI imports instead of loading the plugin.
_CLI_COMMAND_SETUP_RE = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*:[A-Za-z_]\w*")


def cli_command_entry(item: object) -> Optional[dict[str, str]]:
    """``{name, help, description, parent}`` from a cli_commands item; None when a name is invalid.

    ``parent`` names a built-in command the verb attaches under (``hermes <parent> <name>``); empty
    for a top-level ``hermes <name>``. An optional ``setup: "<module>:<function>"`` is carried as a
    fifth key, ``setup`` (``RT-HARNESS-PARSER-PLUGIN-LOAD-TWICE``): the CLI builds the command's parser
    by importing that one function — ``function(parser)``, which sets its own ``func=`` — and never
    loads the plugin to attach it. A ``setup`` that is not that shape skips the row, as a bad name does.
    """
    if not isinstance(item, Mapping):
        return None
    name, parent = item.get("name"), item.get("parent") or ""
    if not all(isinstance(v, str) and _CLI_COMMAND_NAME_RE.fullmatch(v) for v in (name, parent or "x")):
        return None
    entry = {"name": name, "help": str(item.get("help") or ""),
             "description": str(item.get("description") or ""), "parent": parent}
    setup = item.get("setup")
    if setup is not None:
        if not (isinstance(setup, str) and _CLI_COMMAND_SETUP_RE.fullmatch(setup)):
            return None
        entry["setup"] = setup
    return entry


def parse_cli_commands(data: Mapping, key: str, manifest_list: Callable) -> list:
    """The manifest's ``cli_commands`` rows through upstream's list coercer; bad rows warn and skip."""
    return manifest_list(
        data, key, "cli_commands", "a list", cli_command_entry,
        "Plugin %s: cli_commands entry %r needs name (and optional parent) matching [a-z0-9][a-z0-9_-]{0,63}"
        " and, when given, setup as <module>:<function>; skipping",
    )
