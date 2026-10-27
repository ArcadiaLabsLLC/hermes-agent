"""Lens's harness-wide knobs: the ROOT ``config.yaml``'s ``agent_runtime.lens`` block.

Plan ``LENS_EXTENSIONS_2026-10-27.md`` §2 decision 2 and §3 decision 4, defaults from
its §6 (the owner has not ruled; each default is the plan's recommendation):

=====================================  =======  ===========================================
``agent_runtime.lens.<key>``           default  what it bounds
=====================================  =======  ===========================================
``daily_turn_budget``                  96       forged Lens turns per UTC day, all monitors
``host_reads_per_minute_public``       30       reads of one public host per minute
``host_reads_per_minute_private``      120      reads of one opted-in private host
=====================================  =======  ===========================================

Read RAW from the root config, not through a ``RuntimeConfig`` section: a section rides
the ``runtime_config`` wire via ``asdict(cfg)`` (``config/knobs.py`` says the same of
``lean_operative_rules``), and these are serve-side budgets, not snapshot fields. The plan
named ``load_agent_runtime_config``; the tree's wire rule decided otherwise. A missing,
malformed or out-of-range value reads as the default — a config fault never stops the
watcher or the exit door.
"""

from __future__ import annotations

import logging
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)

DEFAULT_DAILY_TURN_BUDGET = 96
DEFAULT_HOST_READS_PER_MINUTE_PUBLIC = 30
DEFAULT_HOST_READS_PER_MINUTE_PRIVATE = 120
#: ``key -> (default, minimum, maximum)``; 0 turns the daily budget into "no turns".
_SETTINGS: dict[str, tuple[int, int, int]] = {
    "daily_turn_budget": (DEFAULT_DAILY_TURN_BUDGET, 0, 100_000),
    "host_reads_per_minute_public": (DEFAULT_HOST_READS_PER_MINUTE_PUBLIC, 1, 6_000),
    "host_reads_per_minute_private": (DEFAULT_HOST_READS_PER_MINUTE_PRIVATE, 1, 6_000),
}


def lens_setting(key: str) -> int:
    """``agent_runtime.lens.<key>`` from the root config, or its default (see the module table)."""

    default, minimum, maximum = _SETTINGS[key]
    try:
        from ..config.loader import harness_root_config_path
        from ..parse_cache import cached_yaml_file

        node: Any = cached_yaml_file(harness_root_config_path(), default=None)
        for part in ("agent_runtime", "lens", key):
            node = node.get(part) if isinstance(node, dict) else None
    except Exception:  # pragma: no cover - defensive; a config fault reads as the default
        logger.debug("lens setting %s failed to load; using the default", key, exc_info=True)
        return default
    if isinstance(node, bool) or not isinstance(node, int) or not minimum <= node <= maximum:
        return default
    return node
