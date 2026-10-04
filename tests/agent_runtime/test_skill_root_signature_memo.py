"""h-chatperf: a warm turn stops re-reading the skill roots, and still sees every edit.

``context_skill_preload_ms`` (683-858) and ``observability_skill_rows_ms``
(417-439) were paid on EVERY turn of the 2026-10-03 cold/warm pair. Three
mechanisms retire most of it, each pinned here with its invalidation:

* the root registry validates on a one-listing signature and REBUILDS (re-filters
  candidates, re-reads frontmatter) only when that signature moves -- pinned by
  the rebuild counter staying at 0 on an unchanged root, and by every kind of
  input edit moving it;
* a turn-scoped registry map reaches resolvers that take none (upstream's
  ``skill_view``), so one turn walks each root once;
* the package content hash enumerates with one ``scandir`` walk and produces the
  SAME digest, in the same file order, as the ``sorted(rglob)`` it replaced.

Named sabotage, one per guarantee:
* ``_skill_root_signature`` returns ``()`` -> the edit rows red (stale registry);
* drop the org-marker stamp from ``_skill_root_signature`` -> the marker row reds;
* ``_registries_for_call`` ignores the scope -> the scope row reds;
* drop the ``name in excluded`` prune in ``_package_file_stamps`` -> the
  digest-equivalence row reds.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from agent import skill_utils
from agent_runtime import skill_resolution as sr


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _skill(root: Path, name: str, *, declared: str | None = None) -> Path:
    front = f"---\nname: {declared or name}\n---\nbody\n"
    return _write(root / name / "SKILL.md", front)


def _bump(path: Path, ns: int) -> None:
    os.utime(path, ns=(ns, ns))


@pytest.fixture()
def root(tmp_path):
    root = tmp_path / "skills"
    _skill(root, "alpha")
    _skill(root / "cat", "beta")
    _write(root / "loose.md", "legacy flat skill")
    sr._skill_root_registry_cache_clear()
    sr._walk_state.rebuilds = 0
    return root


def _rebuilds() -> int:
    return sr.skill_root_rebuilds_this_thread()


def test_an_unchanged_root_is_validated_without_a_rebuild(root):
    first = sr._skill_root_registry(root)
    assert _rebuilds() == 1
    for _ in range(3):
        assert sr._skill_root_registry(root) is first
    assert _rebuilds() == 1, "an unchanged root must not re-filter or re-read anything"


@pytest.mark.parametrize("edit", ["frontmatter", "new_legacy", "delete", "new_package"])
def test_every_input_edit_rebuilds_the_registry(root, edit):
    first = sr._skill_root_registry(root)
    if edit == "frontmatter":
        manifest = root / "alpha" / "SKILL.md"
        manifest.write_text("---\nname: renamed-alpha\n---\nbody changed\n", encoding="utf-8")
        _bump(manifest, 7_000_000_000)
    elif edit == "new_legacy":
        _write(root / "cat" / "another.md", "x")
    elif edit == "delete":
        (root / "loose.md").unlink()
    else:
        _skill(root / "cat", "gamma")
    second = sr._skill_root_registry(root)
    assert second is not first
    assert _rebuilds() == 2
    if edit == "frontmatter":
        assert "renamed-alpha" in second.manifests_by_alias
    if edit == "new_package":
        assert "gamma" in second.manifests_by_alias


def test_the_org_marker_is_part_of_the_signature(root):
    marker = _write(root / skill_utils.ORG_MIRROR_DIR_NAME / skill_utils.ORG_ACTIVE_MARKER, "org-1")
    first = sr._skill_root_registry(root)
    marker.write_text("org-22", encoding="utf-8")  # an org switch: no markdown moved
    assert sr._skill_root_registry(root) is not first


def test_the_turn_scope_reaches_a_resolver_that_takes_no_map(root, monkeypatch):
    monkeypatch.setattr(skill_utils, "get_all_skills_dirs", lambda: [root])
    registries: dict = {}
    sr.reset_skill_root_walks_for_tests()
    with sr.skill_root_registry_scope(registries):
        sr.resolve_skills(["alpha"])
        for _ in range(3):
            assert sr.resolve_skill("alpha").status == "resolved"
    assert sr.skill_root_walks_this_thread() == 1, "one turn, one walk of its one root"
    # Positive control: outside the scope every call walks again.
    sr.reset_skill_root_walks_for_tests()
    sr.resolve_skill("alpha")
    sr.resolve_skill("alpha")
    assert sr.skill_root_walks_this_thread() == 2


def _reference_hash(skill_dir: Path) -> str:
    """The pre-h-chatperf enumeration, verbatim in shape: the oracle."""

    files = [
        path
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file()
        and not any(
            part.startswith(".") or part in skill_utils.EXCLUDED_SKILL_DIRS
            for part in path.relative_to(skill_dir).parts
        )
    ]
    digest = hashlib.sha256()
    for source in files:
        digest.update("/".join(source.relative_to(skill_dir).parts).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(source.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def test_package_hash_matches_the_rglob_enumeration(tmp_path):
    package = tmp_path / "pkg"
    _write(package / "SKILL.md", "---\nname: pkg\n---\n")
    _write(package / "references" / "B.md", "b")
    _write(package / "references" / "a.md", "a")
    _write(package / "scripts" / "run.py", "print(1)")
    _write(package / "Zed.txt", "z")
    _write(package / ".hidden" / "secret.md", "skipped")
    _write(package / ".dotfile", "skipped")
    # A name the dot-prefix rule does NOT already cover, so the exclusion rule
    # itself is what this row exercises.
    excluded = next(n for n in sorted(skill_utils.EXCLUDED_SKILL_DIRS) if not n.startswith("."))
    _write(package / excluded / "junk.js", "skipped")
    _write(package / "deep" / excluded / "junk.md", "skipped")
    sr._content_hash_cache_clear()
    assert sr.skill_package_content_hash(package, package / "SKILL.md") == _reference_hash(package)
    stamps = [relative for relative, _p, _m, _s in sr._package_file_stamps(package)]
    assert not any(excluded in part.split("/") or part.startswith(".") for part in stamps), stamps
