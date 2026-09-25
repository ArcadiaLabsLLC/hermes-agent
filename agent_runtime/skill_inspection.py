"""Read-only skill facts. The tool owner supplies discovery and resolution.

No preprocessing, credential prompts, usage writes, plugin activation or installs.
Callers bind their profile/workspace scope before entering this service.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

MAX_DOCUMENT_BYTES = 1024 * 1024
__layer__ = "lanes"


class SkillInspectionReason(StrEnum):
    UNAVAILABLE = "unavailable"
    DOCUMENT_TOO_LARGE = "document_too_large"
    RESPONSE_TOO_LARGE = "response_too_large"


class SkillInspectionError(ValueError):
    def __init__(self, reason: SkillInspectionReason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SkillInspection:
    """Read port bound by the existing skill tool, not a second catalog."""

    entries: Callable[[], list[dict[str, Any]]]
    locate: Callable[[str], tuple[Path, str]]
    disabled: Callable[[], set[str]]

    def catalog(self, *, can_load: bool) -> list[dict[str, Any]]:
        disabled = self.disabled()
        return [self._entry(row, disabled, can_load) for row in self.entries()]

    @staticmethod
    def _entry(row: dict, disabled: set[str], can_load: bool) -> dict:
        identifier = row.get("identifier") or row["name"]
        paused = row["name"] in disabled or identifier in disabled
        status = "disabled" if paused else "available" if can_load else "tool_unavailable"
        return {
            "id": identifier, "name": row["name"],
            "description": row.get("description") or "",
            "category": row.get("category") or "", "status": status,
            "tags": row.get("tags") or [],
        }

    def detail(self, identifier: str, *, can_load: bool) -> dict[str, Any]:
        entry = next((row for row in self.catalog(can_load=can_load)
                      if row["id"] == identifier), None)
        if entry is None:
            raise SkillInspectionError(SkillInspectionReason.UNAVAILABLE)
        path, source = self.locate(identifier)
        with path.open("rb") as stream:
            raw = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise SkillInspectionError(SkillInspectionReason.DOCUMENT_TOO_LARGE)
        from agent.skill_utils import parse_frontmatter
        content = raw.decode("utf-8-sig", errors="replace")
        metadata, _body = parse_frontmatter(content)
        return {
            **entry, "content": content, "source": source,
            "contentHash": sha256(raw).hexdigest(),
            "metadata": {key: str(metadata[key]) for key in
                         ("version", "author", "license", "compatibility")
                         if metadata.get(key)},
        }
