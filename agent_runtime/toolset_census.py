"""The census: toolsets a loaded PLUGIN registered that no persona's declaration names.

Slice 2 of the tool-visibility split
(``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md`` §3).
A plugin that registers tools into a toolset nobody declares reaches no persona —
``unbounded`` no longer widens the declaration (S0a A1) — and before this module
nothing said so: a teammate's Lens-as-a-tool plugin never surfaced and no row told
anyone why. The census is that row. Two readers: ``persona tool-diff`` (one persona's
declaration) and the serve boot's ``toolset_census`` log line (every loaded persona).

What counts as "registered" is deliberately the PLUGIN population: the registry after
``hermes_cli.plugins.discover_plugins()``, minus the builtin toolsets the committed
manifest names (``tools.toolset_manifest``), minus ``mcp-*`` (admission's domain) and
minus upstream's include-only composites. The registry also holds builtin toolsets in
any process that imported ``model_tools``; subtracting them keeps the answer the same
in ``tool-diff`` (which never imports it) and in a warm serve (which has), and keeps
the line about what a plugin brought rather than about upstream's own opt-in surface.
Never ``import model_tools`` here (S0a A6a).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .personas import ToolsetDeclaration
from .toolset_names import MCP_TOOLSET_PREFIX

__layer__ = "stores"

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolsetCensus:
    #: Plugin-registered toolset names (builtins, ``mcp-*`` and composites removed).
    registered: tuple[str, ...]
    #: Every expanded toolset the given declarations name.
    declared: tuple[str, ...]
    #: ``registered`` minus ``declared`` — what reaches no persona.
    undeclared: tuple[str, ...]

    def log_line(self) -> str:
        return (
            f"toolset_census registered={len(self.registered)} declared={len(self.declared)} "
            f"undeclared=[{', '.join(self.undeclared)}]"
        )


def _plugin_registered_toolsets() -> set[str]:
    from hermes_cli.plugins import discover_plugins
    from tools.registry import registry
    from tools.toolset_manifest import builtin_toolset_names
    from toolsets import TOOLSETS

    discover_plugins()
    builtin = set(builtin_toolset_names())
    composites = {
        name
        for name, definition in TOOLSETS.items()
        if definition.get("includes") and not definition.get("tools")
    }
    return {
        str(name)
        for name in registry.get_registered_toolset_names()
        if str(name) not in builtin
        and str(name) not in composites
        and not str(name).startswith(MCP_TOOLSET_PREFIX)
    }


def toolset_census(declarations: Iterable[ToolsetDeclaration]) -> ToolsetCensus:
    declared: list[str] = []
    for declaration in declarations:
        for name in declaration.toolsets:
            if name not in declared:
                declared.append(name)
    registered = _plugin_registered_toolsets()
    return ToolsetCensus(
        registered=tuple(sorted(registered)),
        declared=tuple(declared),
        undeclared=tuple(sorted(registered - set(declared))),
    )


def undeclared_registered_toolsets(declarations: Iterable[ToolsetDeclaration]) -> tuple[str, ...]:
    """Plugin-registered toolsets none of ``declarations`` names, sorted."""

    return toolset_census(declarations).undeclared


def log_serve_toolset_census() -> ToolsetCensus | None:
    """The serve boot's receipt: one INFO ``toolset_census`` line over every persona the
    runtime loaded. A log receipt, never a key on the ``ready`` frame. Never raises —
    bookkeeping must not be what fails a boot."""

    try:
        from .config import ensure_persisted_personas, load_agent_runtime_config
        from .persona_profiles import declared_lane_toolsets

        personas = ensure_persisted_personas(load_agent_runtime_config())
        census = toolset_census(declared_lane_toolsets(persona) for persona in personas)
    except Exception:
        _LOGGER.warning("toolset_census could not be computed", exc_info=True)
        return None
    _LOGGER.info(census.log_line())
    return census
