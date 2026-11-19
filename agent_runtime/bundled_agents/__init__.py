"""Agents that ship with Eternia: read from the build, referenced by each install.

Module map:

* :mod:`.catalog` — the shipped definitions (Base Agent, Neko Mission Lead), their
  SOUL files and versions. Pure.
* :mod:`.resolve` — how a referencing record loads (the build's definition laid
  over it), saves (stamped with the build's version), shows in the directory
  (``origin``, ``agent_name``, ``locally_changed``, ``based_on``) and feeds a turn
  its SOUL.

Callers: ``store.AgentStore`` (load / save), ``mission_chat_prompts`` (SOUL),
``instance_catalog`` and ``persona_assignments.summary`` (directory fields),
``fresh_install_seed`` and ``hermes harness init`` (references on a fresh root,
update sync).
"""

from __future__ import annotations

from .catalog import ORIGIN_ETERNIA, SHIPPED_AGENTS, ShippedAgent, shipped_agent
from .resolve import (
    directory_fields,
    is_locally_changed,
    prepare_save,
    reference_record,
    resolve_record,
    shipped_reference,
    shipped_soul_for_turn,
    sync_shipped_agents,
)

__layer__ = "stores"

__all__ = [
    "ORIGIN_ETERNIA",
    "SHIPPED_AGENTS",
    "ShippedAgent",
    "directory_fields",
    "is_locally_changed",
    "prepare_save",
    "reference_record",
    "resolve_record",
    "shipped_agent",
    "shipped_reference",
    "shipped_soul_for_turn",
    "sync_shipped_agents",
]
