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


def skill_inspection_reader():
    """Bind human inspection to the same discovery and collision/trust gates as tools."""
    from agent_runtime._upstream_doors import skills_tool_inspection_doors
    _get_disabled_skill_names = skills_tool_inspection_doors()[2]
    return SkillInspection(_inspection_entries, _inspection_location, _get_disabled_skill_names)


def _inspection_entries():
    from agent.skill_utils import skill_matches_platform
    from agent_runtime._upstream_doors import skills_tool_inspection_doors
    from hermes_cli.plugins import get_plugin_manager
    _find_all_skills, _sort_skills = skills_tool_inspection_doors()[:2]
    rows = _find_all_skills(skip_disabled=True)
    # Only already-registered plugins: opening a browser never activates one.
    for row in get_plugin_manager().list_plugin_skill_metadata():
        if skill_matches_platform(row.get("frontmatter", {})):
            rows.append(dict(row))
    return _sort_skills(rows)


def _inspection_location(identifier):
    from agent_runtime._upstream_doors import skills_tool_inspection_doors
    from agent_runtime.skill_resolution import skill_source_kind
    from hermes_cli.plugins import get_plugin_manager
    _skill_lookup_path_error, _skill_search_dirs, _locate_skill = skills_tool_inspection_doors()[3:]
    if _skill_lookup_path_error(identifier):
        raise SkillInspectionError(SkillInspectionReason.UNAVAILABLE)
    plugin = get_plugin_manager().find_plugin_skill(identifier) if ":" in identifier else None
    if plugin is not None:
        return plugin, "plugin"
    project, roots, _active = _skill_search_dirs()
    error, _directory, document = _locate_skill(identifier, None, project, roots)
    if error is not None:
        raise SkillInspectionError(SkillInspectionReason.UNAVAILABLE)
    source = next((skill_source_kind(root) for root in roots
                   if document.is_relative_to(root)), "external")
    return document, source
