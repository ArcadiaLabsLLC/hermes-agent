"""``plugins/eternia-lens``'s door: the Lens pull-door tools (``agent_runtime.lens.tool``).

The plugin imports this module inside ``register`` only, so the tools load when the plugin registers,
as before. Published in ``hermes_cli/data/plugin_api_fork.json``.
"""

from __future__ import annotations

from agent_runtime.lens.tool import (
    LENS_PROPOSE_REPAIR_SCHEMA,
    LENS_PROPOSE_SCHEMA,
    LENS_READ_SCHEMA,
    LENS_TOOLSET,
    handle_lens_propose,
    handle_lens_propose_repair,
    handle_lens_read,
)

__layer__ = "wiring"
__all__ = [
    "LENS_PROPOSE_REPAIR_SCHEMA",
    "LENS_PROPOSE_SCHEMA",
    "LENS_READ_SCHEMA",
    "LENS_TOOLSET",
    "handle_lens_propose",
    "handle_lens_propose_repair",
    "handle_lens_read",
]
