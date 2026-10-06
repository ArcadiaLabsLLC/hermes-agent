"""The ``# fork seam: h-prompt S3`` line in upstream ``agent/system_prompt.py::_skills_prompt``.

Plan: ``docs/agent-runtime-harness/planned/prompt-surface-2026-10-05.md`` S3. A chat-lane
agent carries ``_chat_lane_compact_skill_categories`` (``agent_runtime.chat_lane_skill_index``);
the seam unions it into upstream's own ``compact_categories``, so every category holding none of
the persona's skills renders names-only. An agent without the attribute renders exactly as
upstream renders it.

Killing mutation (run, see the CHANGE commit): delete the seam line -> the union test reds.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent import prompt_builder as _pb
from agent import system_prompt
from agent_runtime.chat_lane_skill_index import COMPACT_ATTR, compact_skill_categories


def _write_skill(root, rel: str, name: str, desc: str) -> None:
    path = root / rel / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n", encoding="utf-8")


@pytest.fixture
def captured(monkeypatch):
    seen: dict = {}

    def fake_build(**kwargs):
        seen.update(kwargs)
        return "INDEX"

    monkeypatch.setattr(_pb, "build_skills_system_prompt", fake_build)
    monkeypatch.setattr(
        "agent.coding_context.coding_compact_skill_categories", lambda **_kw: frozenset({"gaming"})
    )
    return seen


def _agent(**extra):
    return SimpleNamespace(valid_tool_names={"skill_view", "skills_list"}, platform="tool", **extra)


def test_the_seam_unions_the_chat_lane_categories_into_upstreams(captured):
    system_prompt._skills_prompt(_agent(**{COMPACT_ATTR: frozenset({"creative", "media"})}))
    assert captured["compact_categories"] == frozenset({"gaming", "creative", "media"})


def test_without_the_attribute_the_call_is_upstreams(captured):
    system_prompt._skills_prompt(_agent())
    assert captured["compact_categories"] == frozenset({"gaming"})


def test_a_non_frozenset_attribute_is_ignored(captured):
    # A Mock agent (upstream's own test doubles) answers every getattr; the seam must not iterate it.
    agent = _agent(**{COMPACT_ATTR: Mock()})
    system_prompt._skills_prompt(agent)
    assert captured["compact_categories"] == frozenset({"gaming"})


def test_the_rendered_index_keeps_the_persona_category_in_full_and_names_the_rest(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    _write_skill(skills, "software-development/plan-writing", "plan-writing", "Write a staged plan.")
    _write_skill(skills, "software-development/debugging", "debugging", "Find a root cause.")
    _write_skill(skills, "creative/comic", "comic", "Draw a comic strip.")
    _write_skill(skills, "solo-skill", "solo-skill", "An uncategorised skill.")
    monkeypatch.setattr(_pb, "get_all_skills_dirs", lambda: [skills], raising=False)

    demote = compact_skill_categories(["plan-writing", "debugging"], roots=[skills])
    assert demote == frozenset({"creative", "solo-skill"})

    _pb.clear_skills_system_prompt_cache() if hasattr(_pb, "clear_skills_system_prompt_cache") else None
    rendered = _pb.build_skills_system_prompt(
        available_tools={"skill_view"}, available_toolsets={"skills"},
        compact_categories=demote, skills_dir_override=skills,
    )
    assert "    - plan-writing: Write a staged plan." in rendered
    assert "    - debugging: Find a root cause." in rendered
    assert "  creative [names only]: comic" in rendered
    assert "  solo-skill [names only]: solo-skill" in rendered
    assert "Draw a comic strip." not in rendered
