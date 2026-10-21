"""Eternia Lens — the ingest-and-trigger module (plan ``docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md``).

A Python port of Companion's Monitoring contracts. Modules, lowest layer first:

==============  ======  ======================================================
module          layer   owns
==============  ======  ======================================================
wire_value      models  strict bounded canonical JSON; typed ``WireRefusal``
feed            models  feed kinds and their source blocks; ``Observation``
manifest        models  the closed Monitor manifest and automation policy
rules           models  the closed rule schema and the deterministic (pure) evaluator
seal            models  sealed bytes + sha256 + revision
episode         policy  Episodes and the pure observe transition
evidence        policy  the bounded half-open evidence window
==============  ======  ======================================================
"""

from __future__ import annotations

__layer__ = "models"
