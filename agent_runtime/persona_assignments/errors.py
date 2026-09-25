"""The three refusals the persona-instance store raises: a stale model-override
write, a refused retire, and a write against a retired instance.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from agent_runtime.errors import AgentRuntimeError
from agent_runtime.models import PersonaInstance

__layer__ = "models"

__all__ = [
    "PersonaInstanceRetireError",
    "RetiredPersonaInstanceError",
    "StaleModelOverrideWrite",
]


class StaleModelOverrideWrite(AgentRuntimeError):
    """A model-override write carried an ``issued_at`` older than (or equal to)
    the last applied model write for the instance. The newer value wins; the
    stale intent must never be applied silently (supersede guard, mirroring the
    Stage 13 scope-flip fix)."""

    def __init__(self, instance: PersonaInstance, *, issued_at: datetime, applied_issued_at: datetime):
        super().__init__("model_override_write_superseded")
        self.instance = instance
        self.issued_at = issued_at
        self.applied_issued_at = applied_issued_at


class PersonaInstanceRetireError(AgentRuntimeError):
    """A persona-instance retire (end-of-life) was refused by a state guard.

    ``code`` is the machine-readable typed reason every surface (CLI JSON,
    launcher bridge) keys on — never a bare string:

    - ``not_found`` — no such live row.
    - ``canonical_persona_channel`` — the row IS the persona/profile's canonical
      operator channel (the global singleton ``persona_instance_id_for(persona)``).
      Its retirement is the queued workspace-scoping redesign, not this verb.
    - ``instance_active`` — a live run/worker still resolves for the instance;
      never archive a working agent.

    AX2 (2026-08-31) retired the two ASSIGNMENT arms — ``assignment_active`` and
    ``assignments_unknowable``. The first fenced "a live assignment would be
    orphaned"; S70 deleted the store's mint side and the 2026-07-30 chat-only
    purge deleted the lane that consumed assignments, so no row it could orphan
    can be created and none that survives is bound to anything that runs. The
    second existed only to keep the first's NEGATIVE honest — "I could not look"
    must not read as "I looked and found none" — so it had nothing left to
    protect once the first went, and the pair leaves as one decision rather than
    two. Both are rowed in the tombstone registry; the launcher's decodes for
    them leave with this landing.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        persona_instance_id: str,
        detail: dict[str, Any] | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.message = message
        self.persona_instance_id = persona_instance_id
        self.detail = detail or {}


class RetiredPersonaInstanceError(AgentRuntimeError):
    """A saved chat tried to recreate an instance whose placement ended.

    Retirement preserves the row under ``persona_instances_archive`` so chat
    history remains inspectable, but the archived row is also the durable
    end-of-life marker. Reopening that old session must never mint the row back
    into the live roster.
    """

    def __init__(self, persona_instance_id: str, *, archive_path: Path):
        super().__init__("retired_persona_instance")
        self.code = "retired_persona_instance"
        self.persona_instance_id = persona_instance_id
        self.archive_path = archive_path
