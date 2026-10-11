"""D1.05 CF-2 — a new process reads the skill frontmatter an earlier process parsed.

The frontmatter memo (``parse_cache.cached_by_mtime``) is per process, so every
serve boot and every CLI child parsed every SKILL.md again (~2,000 parses,
~4.8 s on the operator's store). ``parse_cache.DiskTier`` persists the parsed
frontmatter at ``<store_root>/derived_cache/skill_frontmatter.json``, validated
per entry by the memo's own file stamp, written back only on the idle keeper's
tick. The cache dir is excluded from realm sync (pinned here) and from the core
cache's store-root fingerprint (pinned by its real writer in
``test_core_cache_exclusions.py``'s ``derived_cache`` driver); owner ruling
2026-10-10: beside ``core_cache``.

Killing mutation: skip the disk read on a cold memo miss (``DiskTier.get``
returns the miss sentinel) -> the child interpreter parses all 40 manifests.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime import idle_turn_keeper, parse_cache, paths
from agent_runtime import skill_resolution as sr

_MANIFESTS = 40
_REPO = Path(__file__).resolve().parents[2]

#: The child counts ``parse_frontmatter`` calls across one registry build plus
#: one compatibility pass, and prints the count as its last line.
_CHILD = """
import sys
from pathlib import Path
from agent import skill_utils
from agent_runtime import skill_resolution as sr
calls = [0]
real = skill_utils.parse_frontmatter
def counting(content):
    calls[0] += 1
    return real(content)
skill_utils.parse_frontmatter = counting
root = Path(sys.argv[1])
registry = sr._skill_root_registry(root)
for skill_dir, manifest in registry.manifests:
    sr.skill_runtime_compatibility(sr.SkillResolutionCandidate(root, skill_dir, manifest, "t"), surface="chat")
assert "declared-07" in registry.manifests_by_alias
print(calls[0])
"""


def _cache_file() -> Path:
    return paths.derived_cache_dir() / "skill_frontmatter.json"


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    paths.store_root().mkdir(parents=True, exist_ok=True)
    root = tmp_path / "skills"
    for index in range(_MANIFESTS):
        manifest = root / f"skill-{index:02d}" / "SKILL.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(f"---\nname: declared-{index:02d}\n---\nbody {index}\n", encoding="utf-8")
    sr._skill_root_registry_cache_clear()
    parse_cache.clear_parse_cache()
    idle_turn_keeper.reset_for_tests()
    yield root
    sr._skill_root_registry_cache_clear()
    parse_cache.clear_parse_cache()
    idle_turn_keeper.reset_for_tests()


def _build(root: Path) -> None:
    registry = sr._skill_root_registry(root)
    for skill_dir, manifest in registry.manifests:
        sr.skill_runtime_compatibility(sr.SkillResolutionCandidate(root, skill_dir, manifest, "t"), surface="chat")


def _child_parses(root: Path) -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_REPO), env.get("PYTHONPATH")]))
    done = subprocess.run(
        [sys.executable, "-c", _CHILD, str(root)],
        cwd=str(_REPO), env=env, capture_output=True, text=True, timeout=110,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return int(done.stdout.strip().splitlines()[-1])


@pytest.mark.timeout(240)
def test_a_child_process_reuses_the_parent_parses_and_reparses_only_an_edit(root):
    _build(root)
    assert sr.flush_skill_frontmatter_disk_cache() is True
    stored = json.loads(_cache_file().read_text(encoding="utf-8"))
    assert len(stored["entries"]) == _MANIFESTS

    assert _child_parses(root) == 0, "a primed derived cache must spare the child every parse"

    edited = root / "skill-03" / "SKILL.md"
    edited.write_text("---\nname: declared-03\ndescription: edited\n---\nnew body\n", encoding="utf-8")
    os.utime(edited, ns=(9_000_000_000, 9_000_000_000))
    assert _child_parses(root) == 1, "exactly the edited manifest misses its stamp and re-parses"


def test_the_write_back_waits_for_the_idle_tick(root):
    _build(root)
    assert not _cache_file().exists(), "a build must never write the cache on its own thread"

    refreshed, _ = idle_turn_keeper.tick_once()

    assert "skill_frontmatter_disk" in refreshed
    assert len(json.loads(_cache_file().read_text(encoding="utf-8"))["entries"]) == _MANIFESTS
    assert idle_turn_keeper.tick_once()[0] == [], "nothing new to write: the second tick is a no-op"


def test_a_stale_stamp_misses_and_a_corrupt_file_is_ignored(root, monkeypatch):
    _build(root)
    sr.flush_skill_frontmatter_disk_cache()
    manifest = root / "skill-00" / "SKILL.md"
    stored = json.loads(_cache_file().read_text(encoding="utf-8"))
    row = stored["entries"][str(manifest)]
    row[1] = {"name": "poisoned"}
    row[0][-1] += 1  # a different size: this entry describes other bytes
    _cache_file().write_text(json.dumps(stored), encoding="utf-8")
    parse_cache.clear_parse_cache()

    assert sr._cached_skill_frontmatter(manifest)["name"] == "declared-00"

    _cache_file().write_text("{not json", encoding="utf-8")
    parse_cache.clear_parse_cache()
    assert sr._cached_skill_frontmatter(manifest)["name"] == "declared-00"


def test_a_value_json_would_change_is_served_but_never_persisted(root, monkeypatch):
    from agent import skill_utils

    dated = root / "skill-05" / "SKILL.md"
    real = skill_utils.parse_frontmatter

    def with_date(content):
        frontmatter, body = real(content)
        if "declared-05" in content:
            frontmatter = {**frontmatter, "released": datetime.date(2026, 10, 10)}
        return frontmatter, body

    monkeypatch.setattr(skill_utils, "parse_frontmatter", with_date)
    assert sr._cached_skill_frontmatter(dated)["released"] == datetime.date(2026, 10, 10)
    sr._cached_skill_frontmatter(root / "skill-06" / "SKILL.md")
    assert sr.flush_skill_frontmatter_disk_cache() is True

    entries = json.loads(_cache_file().read_text(encoding="utf-8"))["entries"]
    assert str(dated) not in entries
    assert str(root / "skill-06" / "SKILL.md") in entries


def test_the_derived_cache_never_syncs(root):
    from agent_runtime import realm_sync

    assert realm_sync._is_hard_excluded_path(f"{paths.DERIVED_CACHE_DIRNAME}/skill_frontmatter.json")
    assert realm_sync._is_hard_excluded_path("skills/alpha/SKILL.md") is False
