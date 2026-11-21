"""The fork plugins' published doors into the fork runtime — one module per fork plugin.

A fork plugin (``plugins/eternia-harness/``, ``plugins/eternia-lens/``) is a Hermes module: upstream's
boundary lint (``scripts/boundary_lint.py``) and ``hermes plugins validate`` count every import it makes
of a Hermes package that is not on the published plugin API. ``agent_runtime`` ships as a Hermes
package, so a plugin importing it directly read as a core-internal crossing. Each plugin imports the
fork runtime ONLY through its door here, and the doors are the only fork names on the published surface
(``hermes_cli/data/plugin_api_fork.json``, read beside upstream's ``plugin_api.json``). Plan:
``docs/agent-runtime-harness/planned/fork-plugins-public-doors-2026-11-21.md``.

Layer: ``wiring`` — a door re-exports from any lower layer, and only the plugins import it.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

__layer__ = "wiring"


def lazy_door(module: str, table: Mapping[str, str]) -> Callable[[str], Any]:
    """A module ``__getattr__`` (PEP 562) serving ``table``'s names on first use: ``name`` ->
    ``"<module>"`` (the same name there) or ``"<module>:<attr>"`` (renamed at the door). Nothing is
    imported until a name is read, so a plugin that imports its door lazily keeps costing nothing at
    plugin discovery."""

    def __getattr__(name: str) -> Any:
        spec = table.get(name)
        if spec is None:
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        source, _, attr = spec.partition(":")
        return getattr(importlib.import_module(source), attr or name)

    return __getattr__
