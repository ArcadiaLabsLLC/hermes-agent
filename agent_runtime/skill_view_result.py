"""The harness's ``skill_view`` result, applied through upstream's ``transform_tool_result`` hook.

Two things the fork used to write inside ``tools/skills_tool.py::skill_view`` and
``tools/skills_tool_plugin.py::_serve_plugin_skill`` (plugin-fit PF-3):

* the runtime-compatibility refusal — a skill whose ``metadata.hermes.surfaces`` /
  ``modes`` exclude the active surface or mode (``skill_resolution.skill_runtime_scope``)
  comes back as the typed ``readiness_status: unsupported`` failure instead of its
  content (for plugin skills and linked-file views too);
* three additive fields on a served filesystem skill: ``resolution_status``,
  ``source_kind`` and ``content_hash``.

The frontmatter is read from the SKILL.md the result names (upstream's own
``_source_path`` field, or the plugin registry's public ``find_plugin_skill``) with
upstream's public ``agent.skill_utils.parse_frontmatter``. This covers the MODEL path
only: a direct in-process ``skill_view`` caller sees the skill (plugin-fit §4 Q3). A
result this cannot read (not JSON, a failure, no path) is left alone.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

__layer__ = "lanes"

logger = logging.getLogger(__name__)

_UNSUPPORTED = "unsupported"


def _skill_md(args: dict, payload: dict) -> tuple[Path | None, bool]:
    """(the SKILL.md this result served from, whether it is a plugin skill)."""
    name = str(args.get("name") or "")
    if ":" in name:
        try:
            from hermes_cli.plugins import get_plugin_manager

            found = get_plugin_manager().find_plugin_skill(name)
        except Exception:
            found = None
        if found is not None:
            return Path(found), True
    source = payload.get("_source_path")
    if not isinstance(source, str) or not source:
        return None, False
    path = Path(source)
    file_path = args.get("file_path")
    if file_path:  # a linked-file view: _source_path is the file, the skill is above it
        for _ in Path(str(file_path)).parts:
            path = path.parent
        path = path / "SKILL.md"
    return path, False


def _frontmatter(skill_md: Path) -> dict:
    from agent.skill_utils import parse_frontmatter

    try:
        frontmatter, _body = parse_frontmatter(skill_md.read_text(encoding="utf-8-sig", errors="replace"))
    except OSError:
        return {}
    return frontmatter if isinstance(frontmatter, dict) else {}


def _source_kind(skill_md: Path) -> str:
    from agent.skill_utils import get_all_skills_dirs, get_project_skills_dirs
    from agent_runtime.skill_resolution import skill_source_kind

    for root in [*get_project_skills_dirs(), *get_all_skills_dirs()]:
        try:
            if skill_md.resolve().is_relative_to(root.resolve()):
                return skill_source_kind(root)
        except OSError:
            continue
    return "external"


def transform_skill_view_result(tool_name: Any = None, args: Any = None, result: Any = None, **_kwargs: Any) -> str | None:
    """``transform_tool_result`` hook: refuse an incompatible skill, stamp a served one."""
    if tool_name != "skill_view" or not isinstance(result, str):
        return None
    try:
        payload = json.loads(result)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return None
    args = args if isinstance(args, dict) else {}
    skill_md, is_plugin = _skill_md(args, payload)
    if skill_md is None or not skill_md.is_file():
        return None

    from agent_runtime.skill_resolution import (
        current_skill_runtime_context, skill_frontmatter_runtime_compatibility, skill_package_content_hash,
    )

    active_surface, root_node_mode = current_skill_runtime_context()
    if active_surface:
        compatibility = skill_frontmatter_runtime_compatibility(
            _frontmatter(skill_md), surface=active_surface, root_node_mode=root_node_mode)
        if not compatibility.get("compatible"):
            name = payload.get("name") or args.get("name")
            return json.dumps({
                "success": False,
                "error": f"Skill '{name}' is not available on the active {active_surface} surface.",
                "reason": compatibility.get("reason"), "surface": active_surface,
                "mode": "root_node" if root_node_mode else "standard",
                "readiness_status": _UNSUPPORTED,
            }, ensure_ascii=False)
    if is_plugin or args.get("file_path"):
        return None
    skill_dir = payload.get("skill_dir")
    try:
        stamped = {
            "resolution_status": "resolved",
            "source_kind": _source_kind(skill_md),
            "content_hash": skill_package_content_hash(Path(skill_dir) if skill_dir else None, skill_md),
        }
    except Exception:
        logger.debug("skill_view stamp failed for %s", skill_md, exc_info=True)
        return None
    return json.dumps({**stamped, **payload}, ensure_ascii=False)
