"""Is the live copy of a skill older than the source that ships it? (RT-SKILL-FRESHNESS-CHECK)

A launcher-authored skill (``launcher-mcp-operations``) is authored in the launcher
repository and reaches an agent only after a hash-guarded promotion into the shared
skills root, or a realm pull. Both doors refuse to overwrite a diverged live copy
(``hold_divergent``), which is right — and until now silent: an agent ran a stale manual
and nobody told it. This module answers the one question, from the package's own
``version:`` frontmatter (flutter_scene's ``skills --check`` rule):

* the live copy is the canonical package under the shared skills root;
* a SHIPPED copy is the directory the live one was last promoted ``--from-path``
  (``skill_promotion.promotion_source_path`` — the launcher checkout) and every realm
  inbox copy of the same slug (what a realm publishes, held or not yet promoted).

A shipped copy whose version is HIGHER than the live one makes the live copy stale. An
unparseable or missing version on a shipped copy says nothing (no claim from no
evidence); a live copy with no version and a shipped one with a version is stale.
Read-only: nothing here promotes, and nothing here may fail a turn.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

__layer__ = "stores"

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


@dataclass(frozen=True, slots=True)
class StaleSkill:
    """``skill``'s live copy at ``live_version`` (None: it declares none) is behind
    ``shipped_version`` at ``source`` (``path:<dir>`` or ``realm:<token>``)."""

    skill: str
    live_version: str | None
    shipped_version: str
    source: str


def skill_version(package_dir: Path) -> str | None:
    """The ``version:`` a package's ``SKILL.md`` frontmatter declares, or None."""

    from agent.skill_utils import parse_frontmatter

    try:
        text = (package_dir / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    value = parse_frontmatter(text)[0].get("version")
    if value is None:
        return None
    return str(value).strip() or None


def _version_key(version: str | None) -> tuple[int, ...] | None:
    match = _VERSION_RE.match(version or "")
    if match is None:
        return None
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:  # 2.2 == 2.2.0
        parts.pop()
    return tuple(parts)


def _packages_named(root: Path, skill: str) -> Iterable[Path]:
    from .skill_promotion import iter_skill_packages

    for slug, package_dir in iter_skill_packages(root):
        if slug == skill or slug.rsplit("/", 1)[-1] == skill:
            yield package_dir


def _shipped_copies(skill: str, live_slug: str) -> Iterable[tuple[str, Path]]:
    from .skill_promotion import promotion_source_path, realm_inbox_root

    source = promotion_source_path(live_slug)
    if source is not None and (source / "SKILL.md").is_file():
        yield f"path:{source}", source
    inbox = realm_inbox_root()
    if inbox.is_dir():
        for realm_dir in sorted(inbox.iterdir(), key=lambda p: p.name):
            if realm_dir.is_dir() and not realm_dir.name.startswith("."):
                for package_dir in _packages_named(realm_dir, skill):
                    yield f"realm:{realm_dir.name}", package_dir


def stale_skill(skill: str) -> StaleSkill | None:
    """The newest shipped copy that is ahead of ``skill``'s live copy, or None.

    None too when there is no live copy at all: an absent skill is the skill
    resolver's fact to report, not a freshness one.
    """

    from .profile_home import get_shared_skills_dir
    from .skill_promotion import iter_skill_packages

    live = next(((slug, package_dir) for slug, package_dir in iter_skill_packages(get_shared_skills_dir())
                 if slug == skill or slug.rsplit("/", 1)[-1] == skill), None)
    if live is None:
        return None
    live_slug, live_dir = live
    live_version = skill_version(live_dir)
    live_key = _version_key(live_version) or ()
    newest: StaleSkill | None = None
    for source, package_dir in _shipped_copies(skill, live_slug):
        shipped = skill_version(package_dir)
        key = _version_key(shipped)
        if key is None or key <= live_key:
            continue
        if newest is None or key > (_version_key(newest.shipped_version) or ()):
            newest = StaleSkill(skill, live_version, str(shipped), source)
    return newest


def stale_skills(skills: Iterable[str]) -> list[StaleSkill]:
    """:func:`stale_skill` for each name, in order; a read that fails is logged and skipped."""

    found: list[StaleSkill] = []
    for skill in skills:
        try:
            stale = stale_skill(str(skill))
        except Exception:  # a freshness read must never fail a turn
            logger.debug("skill freshness unavailable for %s", skill, exc_info=True)
            continue
        if stale is not None:
            found.append(stale)
    return found


def render_stale_manual_clause(stale: Iterable[StaleSkill]) -> str:
    """One agent-visible sentence per stale operating manual, ``""`` when none is stale."""

    from .mcp_admission.vocabulary import MCP_OPERATING_SKILL_STALE

    return "".join(
        f" Operating manual {item.skill} is stale ({MCP_OPERATING_SKILL_STALE}): your copy is "
        f"version {item.live_version or 'unversioned'}, the shipped source ({item.source}) is "
        f"version {item.shipped_version}. Where the manual and the surface disagree, trust the "
        "surface, and say in your reply that the manual was stale; only an operator can promote "
        "the new copy (`hermes harness skills promote`)."
        for item in stale
    )


__all__ = ["StaleSkill", "render_stale_manual_clause", "skill_version", "stale_skill", "stale_skills"]
