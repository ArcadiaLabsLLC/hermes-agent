"""The agents Eternia ships: their definitions and versions, read from the build.

Owner rulings 2026-11-19 (Eternia ``Launcher_Brain/20 — Active Initiatives/
bundled-agents-stay-one-agent-design.md`` § 9): only Base Agent and Neko Mission
Lead ship; shipped agents always update and nobody pins a version; a local change
to one is allowed and is reset by the next update.

A shipped agent's DEFINITION is the fields in :data:`DEFINITION_FIELDS` plus its
SOUL text. Everything else on a persona record — model, provider, reasoning mode,
budgets, repo scope, character — is an install SETTING the record keeps.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__layer__ = "policy"

__all__ = [
    "DEFINITION_FIELDS",
    "ORIGIN_ETERNIA",
    "SHIPPED_AGENTS",
    "ShippedAgent",
    "normalized_soul_sha",
    "shipped_agent",
]

ORIGIN_ETERNIA = "eternia"

#: What a shipped agent IS; a difference in any of these is a change to the agent.
DEFINITION_FIELDS: tuple[str, ...] = (
    "display_name",
    "role",
    "autonomy",
    "hermes_profile",
    "skills",
    "system_prompt_path",
    "soul_overlay_path",
    "required_mcp_servers",
    "include_profile_memory",
    "include_core_context_files",
)

_SOULS = Path(__file__).resolve().parent.parent / "seed_souls"


def normalized_soul_sha(text: str) -> str:
    """The content hash two SOUL texts compare by (line endings and outer space ignored)."""

    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ShippedAgent:
    id: str
    definition: dict[str, Any]
    #: The SOUL file under ``agent_runtime/seed_souls/``; ``None`` leaves the
    #: profile's own ``SOUL.md`` in charge (Base: the protocol-layer profile the
    #: owner ruled stays as it is, 2026-11-18).
    soul_file: str | None = None
    #: Hashes of SOUL texts earlier builds shipped, so a profile still holding one
    #: reads as unchanged rather than as a local edit.
    earlier_soul_sha256: tuple[str, ...] = field(default=())

    @property
    def name(self) -> str:
        return str(self.definition["display_name"])

    def soul_text(self) -> str | None:
        if self.soul_file is None:
            return None
        return (_SOULS / self.soul_file).read_text(encoding="utf-8")

    def known_soul_sha256(self) -> frozenset[str]:
        soul = self.soul_text()
        current = (normalized_soul_sha(soul),) if soul is not None else ()
        return frozenset((*current, *self.earlier_soul_sha256))

    @property
    def version(self) -> str:
        """One hash of the definition and SOUL this build ships."""

        body = json.dumps(
            {"definition": self.definition, "soul": self.soul_text()},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


SHIPPED_AGENTS: tuple[ShippedAgent, ...] = (
    ShippedAgent(
        id="neko_supervisor",
        definition={
            "display_name": "Neko Mission Lead",
            # The canonical spelling of the alice/neko supervisor pair: the
            # terminal-envelope grant table keys on it.
            "role": "alice_supervisor",
            "autonomy": "propose_only",
            "hermes_profile": "neko",
            "skills": ["harness-runtime-model"],
            "system_prompt_path": "",
            "soul_overlay_path": "SOUL.md",
            "required_mcp_servers": [],
            "include_profile_memory": True,
            "include_core_context_files": False,
        },
        soul_file="neko.md",
    ),
    ShippedAgent(
        id="base",
        # Seen in data 2026-11-19: the record every Eternia install has carried
        # over the ``base`` profile (Eternia's bundled profile).
        definition={
            "display_name": "Base Agent",
            "role": "profile",
            "autonomy": "propose_only",
            "hermes_profile": "base",
            "skills": ["harness-runtime-model", "harness-charsheet-authoring"],
            "system_prompt_path": "",
            "soul_overlay_path": None,
            "required_mcp_servers": [],
            "include_profile_memory": True,
            "include_core_context_files": False,
        },
    ),
)

_BY_ID = {agent.id: agent for agent in SHIPPED_AGENTS}


def shipped_agent(persona_id: str | None) -> ShippedAgent | None:
    return _BY_ID.get(str(persona_id or ""))
