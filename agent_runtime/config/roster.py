"""The persona roster READ: the persisted persona store merged over the config records.

Map: ``agent_runtime/config/__init__.py``. This is the one module in the config
package that reads a store, which is why it sits at ``stores`` and the pure
merge it calls (``persona_records``) stays at ``policy``. A ``policy`` module
that needs the roster takes it as an argument from its ``stores``-layer caller
(``persona_assignments.summary``'s ``roster=``) rather than importing this.
"""

from __future__ import annotations

from typing import Any

from .loader import load_agent_runtime_config
from .persona_records import merge_persisted_personas, skill_sources_for
from .schema import AgentRuntimeConfig

__layer__ = "stores"

__all__ = ["ensure_persisted_personas", "persona_skill_sources"]


def _stored_personas():
    from ..store import AgentStore

    return AgentStore().list_all()


def ensure_persisted_personas(cfg: AgentRuntimeConfig | None = None):
    """Return the persisted persona store plus data-declared config records."""

    cfg = cfg or load_agent_runtime_config()
    return merge_persisted_personas(_stored_personas(), cfg)


def persona_skill_sources(cfg: AgentRuntimeConfig | None = None) -> dict[str, dict[str, Any]]:
    """Which tier answered each persona's ``skills`` (``persona_records.skill_sources_for``)."""

    cfg = cfg or load_agent_runtime_config()
    return skill_sources_for(_stored_personas(), cfg)
