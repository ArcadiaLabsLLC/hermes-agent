"""The harness agents' background review: prompts without the always-write push, measured timings,
and no direct write to a shared skill (RT-REVIEW-WRITE-BIAS-UPSTREAM, RT-CURATOR-COST-FROM-TURN-RECORD,
RT-REVIEW-SHARED-SKILL-GATE).

Each test names the mutation that kills it (recorded in the landing commit).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime import review_prompts
from agent_runtime.persona_turn_binding import bind_persona_turn_agent
from agent_runtime.review_skill_gate import review_shared_skill_write


# Mutation: drop a ``PUSH_CUTS`` row -> its phrase survives in a harness prompt. The upstream
# half is the positive control: if upstream stops pushing, this test says so instead of passing.
def test_the_harness_prompts_cut_upstreams_push_and_add_the_claims_rule():
    from agent.background_review import _COMBINED_REVIEW_PROMPT, _SKILL_REVIEW_PROMPT

    assert review_prompts.remaining_push(_SKILL_REVIEW_PROMPT)
    assert review_prompts.remaining_push(_COMBINED_REVIEW_PROMPT)
    for prompt in review_prompts.harness_review_prompts():
        assert review_prompts.remaining_push(prompt) == []
        assert review_prompts.VERIFIABLE_CLAIMS_BLOCK in prompt
        assert "Nothing to save." in prompt


# Mutation: fold the PRINTED clock instead of the hook's ``duration_ms`` (or skip the re-arm)
# -> the 202601 ms row is missing from the prompt upstream's spawn reads.
def test_a_turns_measured_timings_reach_the_prompt_upstreams_spawn_reads():
    from agent.background_review import spawn_background_review_thread

    agent = SimpleNamespace(_persona_chat_turn_id="turn-1")
    with bind_persona_turn_agent(agent):
        review_prompts.on_post_tool_call(
            tool_name="terminal", args={"command": "flutter test x_test.dart"},
            result=json.dumps({"output": "00:01 +1: All tests passed!", "exit_code": 0}), duration_ms=202601)
        review_prompts.on_post_tool_call(
            tool_name="terminal", args={"command": "grep -rn x lib"},
            result=json.dumps({"output": "", "exit_code": 124}), duration_ms=60883)
    _target, prompt = spawn_background_review_thread(agent, [], review_skills=True, task_cfg={})
    assert prompt == agent._SKILL_REVIEW_PROMPT
    assert "terminal 202601 ms exit 0: flutter test x_test.dart" in prompt
    assert "terminal 60883 ms TIMED OUT exit 124: grep -rn x lib" in prompt
    assert prompt.index("202601 ms") < prompt.index("60883 ms")  # slowest first
    assert "2 call(s), 263484 ms in tools" in agent._COMBINED_REVIEW_PROMPT

    agent._persona_chat_turn_id = "turn-2"  # a new turn starts a new ledger
    review_prompts.arm_review_prompts(agent)
    assert "202601" not in agent._SKILL_REVIEW_PROMPT
    assert "none recorded — write no cost" in agent._SKILL_REVIEW_PROMPT


@pytest.fixture
def skill_roots(tmp_path, monkeypatch):
    home, shared = tmp_path / "home", tmp_path / "shared"
    (home / "skills" / "local-skill").mkdir(parents=True)
    (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    (shared / "shared-skill").mkdir(parents=True)
    body = "---\nname: {0}\ndescription: d\n---\n\nIt takes a few seconds.\n"
    (home / "skills" / "local-skill" / "SKILL.md").write_text(body.format("local-skill"), encoding="utf-8")
    (shared / "shared-skill" / "SKILL.md").write_text(body.format("shared-skill"), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_SHARED_SKILLS", str(shared))
    return home, shared


def _patch(name):
    return {"action": "patch", "name": name, "old_string": "a few seconds", "new_string": "about 200 s"}


def _as_review(fn):
    from tools.skill_provenance import reset_current_write_origin, set_current_write_origin

    token = set_current_write_origin("background_review")
    try:
        return fn()
    finally:
        reset_current_write_origin(token)


# Mutation: drop the ``is_relative_to(shared_root)`` test (or the origin check) -> the local
# skill (or the foreground call) is staged too; drop ``stage_write`` -> no pending record.
def test_a_review_write_to_a_shared_skill_is_staged_with_its_prior_text_kept(skill_roots):
    from tools import write_approval as wa
    from tools.skill_manager_tool import apply_skill_pending

    home, shared = skill_roots
    assert review_shared_skill_write("skill_manage", _patch("shared-skill")) is None  # foreground
    assert _as_review(lambda: review_shared_skill_write("skill_manage", _patch("local-skill"))) is None

    directive = _as_review(lambda: review_shared_skill_write("skill_manage", _patch("shared-skill")))

    assert directive["action"] == "block" and "SHARED skill" in directive["message"]
    [record] = wa.list_pending(wa.SKILLS)
    assert record["origin"] == "background_review" and record["id"] in directive["message"]
    assert "a few seconds" in (shared / "shared-skill" / "SKILL.md").read_text(encoding="utf-8")
    [kept] = list((shared / ".archive").iterdir())
    assert "a few seconds" in (kept / "SKILL.md").read_text(encoding="utf-8")
    # Positive control: upstream's approval replay of the staged record performs the write.
    assert json.loads(apply_skill_pending(record["payload"]))["success"] is True
    assert "about 200 s" in (shared / "shared-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_the_plugin_pre_tool_call_hook_returns_the_staged_block(skill_roots):
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eh_plugin_review_gate_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    result = _as_review(lambda: module.refuse_tool_call(tool_name="skill_manage", args=_patch("shared-skill")))
    assert result["action"] == "block" and "Staged for the owner" in result["message"]
