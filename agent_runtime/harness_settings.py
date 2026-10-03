"""The harness's own config keys — ONE reader, under the plugin manifest.

The ruled home of every harness-owned config key is the plugin entry
``plugins.entries.eternia-harness.settings.<name>``, declared in
``plugins/eternia-harness/plugin.yaml``'s ``config_schema`` (so upstream's
loader validates it and the Plugins tab can render it). The keys used to be
top-level blocks nobody declared — ``remote_gateway.*`` and ``charsheet.*`` —
and every reader of a harness setting goes through :func:`harness_setting`.

TRANSITION (stated, not silent). A config that still carries the old
top-level key is READ, not migrated: the new path wins whenever it is present,
and the old key answers only when it is absent. A one-shot migration was
refused because the launcher writes ``remote_gateway.listen`` through
``hermes config set`` on every LAN toggle until its own row lands — a migrated
key would be re-written at the old path the next toggle and then ignored,
switching the operator's listener off under them. The fallback is retired
(``LEGACY_KEYS`` emptied) once the launcher writes the new path; that retirement
is its own runtime-queue row.

Layer: ``models`` — every layer may read a setting. ``hermes_cli.config`` is
imported at CALL time, so a stub on it still reaches the read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__layer__ = "models"

PLUGIN_ID = "eternia-harness"
SETTINGS_PATH = ("plugins", "entries", PLUGIN_ID, "settings")

#: setting name -> the legacy top-level ``(block, key)`` still read during the
#: transition. Every name here is declared in the manifest's ``config_schema``
#: (pinned by tests/agent_runtime/test_harness_settings.py).
LEGACY_KEYS: dict[str, tuple[str, str]] = {
    "remote_gateway_listen": ("remote_gateway", "listen"),
    "remote_gateway_port": ("remote_gateway", "port"),
    "charsheet_provider_timeout_seconds": ("charsheet", "provider_timeout_seconds"),
}


def settings_path(name: str) -> str:
    """The dotted ``hermes config set`` path of one harness setting."""
    return ".".join((*SETTINGS_PATH, name))


def harness_setting(name: str, default: Any = None, *, config: Mapping | None = None) -> Any:
    """``plugins.entries.eternia-harness.settings.<name>``, else the legacy key, else ``default``."""
    if config is None:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly()
    if not isinstance(config, Mapping):
        return default
    settings: Any = config
    for segment in SETTINGS_PATH:
        settings = settings.get(segment) if isinstance(settings, Mapping) else None
    if isinstance(settings, Mapping) and name in settings:
        return settings[name]
    legacy = LEGACY_KEYS.get(name)
    if legacy is not None:
        block = config.get(legacy[0])
        if isinstance(block, Mapping) and legacy[1] in block:
            return block[legacy[1]]
    return default
