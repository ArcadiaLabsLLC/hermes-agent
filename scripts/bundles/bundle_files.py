"""What a bundle directory holds: its layout names, which files ship, and its distributions.

Split out of ``scripts/bundle_profile_package.py`` (W0-G1 size ceiling, row RT-PACKAGER-CEILING-800).
The one owner of the file rules the copy phase (the packager) and the verify phase
(``scripts/bundles/verify.py``) both apply.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scripts.bundle_profile_closure import ROOT, _norm


#: Path components that never ship, first- or third-party.
TEST_DIRS = {"tests", "test", "testing_data"}
NOISE_DIRS = {"__pycache__"}
NOISE_SUFFIXES = (".pyc", ".pyo")
BUNDLE_MANIFEST = "bundle-manifest.json"
BAKED_MARKER = ".hermes-baked-pycache"
#: ``agent_runtime.build_stamp``'s baked stamp, read beside the package when no git is consulted.
BUILD_SHA_FILE = ".hermes_build_sha"
#: Core site-packages file that adds every installed engine pack to the import path at start.
#: ``site`` runs a .pth line that starts with ``import``; a missing directory is skipped, so
#: no pack means the engine's imports fail and its provider reports unavailable.
ENGINE_PACKS_ENV = "HERMES_ENGINE_PACKS"
ENGINE_PACKS_PTH = "hermes-engine-packs.pth"
ENGINE_PACKS_PTH_LINE = (
    f"import os, site; [site.addsitedir(p) for p in os.environ.get({ENGINE_PACKS_ENV!r}, '').split(os.pathsep) "
    "if p and os.path.isdir(p)]\n")
#: Files the packaging step itself writes into a site-packages (owned by no distribution).
PACKAGER_FILES = {ENGINE_PACKS_PTH}
PACK_MANIFEST = "engine-pack.json"


@dataclass
class Dist:
    name: str
    version: str
    info: str  # dist-info directory name
    files: list[str]  # site-relative RECORD paths inside the site directory


def read_site(site: Path) -> dict[str, Dist]:
    """Every ``*.dist-info`` under ``site`` -> :class:`Dist` (normalized name key)."""
    import csv
    from email.parser import HeaderParser

    dists: dict[str, Dist] = {}
    for info in sorted(site.glob("*.dist-info")):
        meta = HeaderParser().parsestr((info / "METADATA").read_text(encoding="utf-8-sig", errors="replace"))
        files: list[str] = []
        record = info / "RECORD"
        if record.is_file():
            with record.open(encoding="utf-8", newline="") as handle:
                files = [row[0].replace("\\", "/") for row in csv.reader(handle) if row]
        files = [f for f in files if not f.startswith("../") and not f.startswith("/")]
        dist = Dist(name=_norm(meta["Name"]), version=meta["Version"], info=info.name, files=files)
        dists[dist.name] = dist
    return dists


def tracked_files(root: Path = ROOT) -> list[str]:
    done = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                          check=True, timeout=120)
    return [p for p in done.stdout.decode("utf-8").split("\0") if p]


def _is_noise(rel: str) -> bool:
    parts = rel.split("/")
    return bool(NOISE_DIRS.intersection(parts)) or rel.endswith(NOISE_SUFFIXES)


def _is_test(rel: str) -> bool:
    return bool(TEST_DIRS.intersection(rel.split("/")[:-1]))


def skill_ships(rel: str, skill_platforms: tuple[str, ...], root: Path = ROOT,
                 _cache: dict | None = None, skill_names: tuple[str, ...] = ()) -> bool:
    """Does a file under ``skills/`` ship? Always, unless the profile names ``skill_platforms``:
    then only when its skill's ``SKILL.md`` frontmatter ``platforms:`` names one of them — the
    existing per-skill OS switch (``agent.skill_utils``), read by the same parser — or its
    frontmatter ``name:`` is one of the profile's ``skill_names`` (the shipped copy is then
    marked for those platforms, :func:`mark_skill_platforms`). A file outside any skill directory
    (a category README) ships only for an unfiltered profile."""
    if not skill_platforms:
        return True
    from agent.skill_utils import parse_frontmatter

    cache = _cache if _cache is not None else {}
    parts = rel.split("/")
    for i in range(len(parts) - 1, 0, -1):
        skill_dir = "/".join(parts[:i])
        if skill_dir not in cache:
            md = root / skill_dir / "SKILL.md"
            if not md.is_file():
                cache[skill_dir] = None
            else:
                front, _ = parse_frontmatter(md.read_text(encoding="utf-8-sig"))
                cache[skill_dir] = ({p.lower() for p in _platforms(front)}, str(front.get("name") or "").strip())
        if cache[skill_dir] is not None:
            listed, name = cache[skill_dir]
            return bool(listed & {p.lower() for p in skill_platforms}) or name in skill_names
    return False


def _platforms(front: dict) -> list[str]:
    listed = front.get("platforms") or []
    return [str(p).strip() for p in (listed if isinstance(listed, list) else [listed])]


_PLATFORMS_KEY = re.compile(r"^platforms:[^\n]*\n(?:[ \t]+-[^\n]*\n)*", re.MULTILINE)


def mark_skill_platforms(text: str, skill_platforms: tuple[str, ...]) -> str:
    """``SKILL.md`` text whose frontmatter ``platforms:`` also names ``skill_platforms``
    (RT-PHONE-SKILLS-NONE-MARKED): what a profile's ``skill_names`` ship as, so upstream's run-time
    per-skill OS switch (``agent.skill_utils.skill_matches_platform``) shows the skill on those
    platforms with no edit to the tracked file or to upstream code. A skill with no ``platforms:``
    already matches every OS and is returned unchanged. Raises when the rewrite does not parse
    back to the union — the bundle then fails loudly rather than shipping a hidden skill."""
    from agent.skill_utils import parse_frontmatter

    listed = _platforms(parse_frontmatter(text)[0])
    missing = [p for p in skill_platforms if p.lower() not in {x.lower() for x in listed}]
    if not listed or not missing:
        return text
    head_end = text.index("\n---", 3) + 1
    union = [*listed, *missing]
    head, count = _PLATFORMS_KEY.subn(lambda _m: f"platforms: [{', '.join(union)}]\n", text[:head_end], count=1)
    marked = head + text[head_end:]
    if count != 1 or [p.lower() for p in _platforms(parse_frontmatter(marked)[0])] != [p.lower() for p in union]:
        raise ValueError(f"cannot mark the skill's platforms {listed} with {missing}")
    return marked


def mark_named_skill(shipped: Path, skill_platforms: tuple[str, ...], skill_names: tuple[str, ...]) -> bool:
    """The copy phase's half: a shipped ``SKILL.md`` whose ``name:`` the profile lists is rewritten
    by :func:`mark_skill_platforms`; any other file is left as copied. -> whether it was rewritten."""
    if not skill_names or shipped.name != "SKILL.md":
        return False
    from agent.skill_utils import parse_frontmatter

    text = shipped.read_text(encoding="utf-8-sig")
    if str(parse_frontmatter(text)[0].get("name") or "").strip() not in skill_names:
        return False
    marked = mark_skill_platforms(text, skill_platforms)
    shipped.write_text(marked, encoding="utf-8", newline="")
    return marked != text


def _data_file(rel: str, excluded: dict[str, str]) -> bool:
    """A tracked non-module file the packager may ship (package data or a resource)."""
    return not (rel.endswith(".py") or _is_noise(rel) or _is_test(rel) or _excluded(f"app/{rel}", excluded))


def _resource_file(rel: str, excluded: dict[str, str]) -> bool:
    """A tracked file under a resource that ships. Unlike package data, a ``.py`` ships: a
    skill's ``scripts/*.py`` are files the skill runs, never modules the closure imports
    (terminal / code_execution are present-but-off features, and present-off code ships)."""
    return not (_is_noise(rel) or _is_test(rel) or _excluded(f"app/{rel}", excluded))


def _in_resource(rel: str, resources: tuple[str, ...]) -> bool:
    """``rel`` lies under a ``packaging.resources`` entry: a top-level resource
    (``skills``) or a repo-relative directory (``docs/agent-runtime-harness/harness-skills``,
    the harness skills :mod:`agent_runtime.skill_install` copies at serve start)."""
    return any(rel.startswith(resource.rstrip("/") + "/") for resource in resources)


def _excluded(rel: str, excluded: dict[str, str]) -> bool:
    """``rel`` is bundle-root-relative (``app/...``, ``site-packages/...``)."""
    return any(rel == pattern or rel.startswith(pattern.rstrip("/") + "/") or fnmatch.fnmatch(rel, pattern)
               for pattern in excluded)
