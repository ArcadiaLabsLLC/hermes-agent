"""The harness's own config keys — ONE reader, under the plugin manifest.

The ruled home of every harness-owned config key is the plugin entry
``plugins.entries.eternia-harness.settings.<name>``, declared in
``plugins/eternia-harness/plugin.yaml``'s ``config_schema`` (so upstream's
loader validates it and the Plugins tab can render it). The keys used to be
top-level blocks nobody declared — ``remote_gateway.*`` and ``charsheet.*`` —
and every reader of a harness setting goes through :func:`harness_setting`.

RETIRED (RT-RETIRE-LEGACY-TOP-LEVEL, 2026-10-25). The old top-level keys are no
longer read: the launcher writes the new path since 290449df44, and
``agent_runtime.harness_settings_legacy`` moves any value still at the old path to
the new one, deletes the old block and reports it, once per config file at plugin
load.

Layer: ``models`` — every layer may read a setting. ``hermes_cli.config`` is
imported at CALL time, so a stub on it still reaches the read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__layer__ = "models"

PLUGIN_ID = "eternia-harness"
SETTINGS_PATH = ("plugins", "entries", PLUGIN_ID, "settings")

def harness_setting(name: str, default: Any = None, *, config: Mapping | None = None) -> Any:
    """``plugins.entries.eternia-harness.settings.<name>``, else ``default``."""
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
    return default
