"""The chat lane's persona-scoped skills index (lane h-prompt-surface, S3).

Plan: ``docs/agent-runtime-harness/planned/prompt-surface-2026-10-05.md`` S3.
Upstream's ``agent/system_prompt.py::_skills_prompt`` renders every category in
full on ``platform=tool`` (the coding-context demotion only engages on the
interactive coding platforms), so a supervisor declaring nine skills paid for a
96-entry index. This module computes the TOP-LEVEL categories that hold none of
the persona's skills and hands them to the agent as
``_chat_lane_compact_skill_categories``; the one guarded seam line in
``_skills_prompt`` (``# fork seam: h-prompt S3``) unions them into upstream's own
``compact_categories``, so those categories collapse to a names-only line.
Nothing is hidden: every name stays in the index and ``skill_view`` is unchanged
(upstream's "never drop entries" rule).

A persona that declares no skills is not scoped (``None``): it has not said
what it uses, so demoting everything would be a guess.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

__layer__ = "stores"

#: The agent attribute the ``_skills_prompt`` seam reads.
COMPACT_ATTR = "_chat_lane_compact_skill_categories"

#: Upstream's org-mirror directory (``agent.prompt_builder.ORG_MIRROR_DIR_NAME``),
#: whose categories are labelled ``org:<id>``.
_ORG_MIRROR_DIR = "_org"


def chat_lane_index_skills(persona: Any, operating_skills: Iterable[str] = ()) -> tuple[str, ...] | None:
    """The skills whose categories stay in full on this persona's chat lane, or None.

    The persona's declared ``skills`` plus the turn's operating manuals (the
    admitted MCP surface's skills, ``chat_lane_bundle.operating_skills``). None
    when the persona declares none — the lane is then left unscoped.
    """

    declared = [str(s).strip() for s in (getattr(persona, "skills", None) or ()) if str(s or "").strip()]
    if not declared:
        return None
    operating = [str(s).strip() for s in (operating_skills or ()) if str(s or "").strip()]
    return tuple(sorted(set(declared) | set(operating)))


def _top_category(manifest: Path, root: Path) -> str:
    """The top-level index category of one ``SKILL.md`` — upstream's
    ``_build_snapshot_entry`` rule, cut at the first ``/`` as the demotion is."""

    parts = manifest.relative_to(root).parts
    if len(parts) >= 3 and parts[0] == _ORG_MIRROR_DIR:
        return f"org:{parts[1]}"
    # Upstream: ``general`` for a bare file, the skill's own directory name for an
    # uncategorised ``<name>/SKILL.md``, else the category path.
    return "general" if len(parts) < 2 else parts[0]


def compact_skill_categories(keep_skills: Iterable[str], roots: list[Path] | None = None) -> frozenset[str]:
    """Every top-level category under ``roots`` that holds none of ``keep_skills``.

    A skill is matched by its directory name or its frontmatter ``name`` (the
    same aliases ``agent_runtime.skill_resolution`` resolves). ``roots`` defaults
    to ``agent.skill_utils.get_all_skills_dirs()`` — call it inside the persona's
    profile context. The per-root registry is the shared, signature-validated
    one, so a warm root costs one listing walk.
    """

    from agent_runtime.skill_resolution import skill_root_manifests, skill_search_roots

    if roots is None:
        roots = skill_search_roots()
    keep = {str(s).strip() for s in keep_skills if str(s or "").strip()}
    all_categories: set[str] = set()
    kept: set[str] = set()
    for root in roots:
        for entry in skill_root_manifests(Path(root)):
            skill_dir, manifest = entry.skill_dir, entry.manifest
            try:
                category = _top_category(manifest, Path(root))
            except ValueError:
                continue
            all_categories.add(category)
            names = set(entry.aliases) | ({skill_dir.name} if skill_dir is not None else set())
            if names & keep:
                kept.add(category)
    return frozenset(all_categories - kept)


def apply_chat_lane_skill_scope(agent: Any, keep_skills: Iterable[str] | None) -> None:
    """Stamp the demotion set on a freshly built chat-lane agent (never raises).

    ``None`` leaves the agent untouched: the index renders exactly as upstream
    renders it.
    """

    if keep_skills is None or agent is None:
        return
    try:
        setattr(agent, COMPACT_ATTR, compact_skill_categories(keep_skills))
    except Exception:
        logger.debug("chat-lane skill scope failed; the index stays unscoped", exc_info=True)


__all__ = [
    "COMPACT_ATTR",
    "apply_chat_lane_skill_scope",
    "chat_lane_index_skills",
    "compact_skill_categories",
]
