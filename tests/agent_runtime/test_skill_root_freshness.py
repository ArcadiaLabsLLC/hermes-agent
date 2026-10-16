"""h-warm-phases: a turn's pre-admit resolves read the process registry, and still see every name.

* a root the process already walked answers a ``TurnRootRegistries`` map without a walk, and is
  queued for the re-walk the turn's ``request_sent`` starts;
* a name the cached registry does not hold (a skill added since) re-walks inline and resolves;
* a resolved file that is gone (a skill deleted since) re-walks inline and reports it missing;
* a plain map (every caller but the turn's pre-admit assembly) walks as before;

Named sabotage: ``needs_fresh_walk`` answering False -> the added/deleted rows red;
``registry_for_turn`` walking -> the no-walk row reds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import mission_chat_phases
from agent_runtime import skill_resolution as sr
from agent_runtime import skill_root_freshness as fresh


def _skill(root: Path, name: str) -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\n---\nbody\n", encoding="utf-8")
    return path


@pytest.fixture()
def root(tmp_path):
    root = tmp_path / "skills"
    _skill(root, "alpha")
    sr._skill_root_registry_cache_clear()
    fresh.reset_for_tests()
    sr.resolve_skills(["alpha"], roots=[root])  # the process has walked it once (prewarm, snapshot)
    sr.reset_skill_root_walks_for_tests()
    yield root
    fresh.reset_for_tests()


def test_a_turn_reads_the_cached_root_and_rewalks_it_after_request_sent(root):
    result = sr.resolve_skills(["alpha"], roots=[root], _root_registries=fresh.TurnRootRegistries())

    assert result["alpha"].status == "resolved"
    assert sr.skill_root_walks_this_thread() == 0
    assert fresh.pending_refreshes_for_tests() == [f"root:{sr._resolved_path(root)}"]

    assert fresh.revalidate_served_roots in mission_chat_phases._REQUEST_SENT_LISTENERS
    thread = fresh.revalidate_served_roots()  # what every turn's request_sent mark runs
    assert thread is not None and thread.name == fresh.REVALIDATE_THREAD_NAME
    thread.join(10)
    assert fresh.pending_refreshes_for_tests() == []
def test_a_skill_added_since_the_last_walk_still_resolves_on_the_turn(root):
    _skill(root, "beta")

    result = sr.resolve_skills(["alpha", "beta"], roots=[root], _root_registries=fresh.TurnRootRegistries())

    assert result["beta"].status == "resolved"
    assert sr.skill_root_walks_this_thread() == 1


def test_a_skill_deleted_since_the_last_walk_reads_missing_on_the_turn(root):
    (root / "alpha" / "SKILL.md").unlink()

    single = sr.resolve_skill("alpha", roots=[root], _root_registries=fresh.TurnRootRegistries())

    assert single.status == "missing"


def test_a_plain_map_still_walks(root):
    sr.resolve_skills(["alpha"], roots=[root], _root_registries={})

    assert sr.skill_root_walks_this_thread() == 1
    assert fresh.pending_refreshes_for_tests() == []
