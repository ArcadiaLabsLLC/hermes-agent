"""Lane h-prompt-surface: stages S3, S4, S6 of the chat turn's prompt surface.

Plan: ``docs/agent-runtime-harness/planned/prompt-surface-2026-10-05.md``.

* S3 — the chat lane names its persona's skill categories; every other category
  renders names-only (``agent_runtime.chat_lane_skill_index``).
* S4 — ``agent_runtime.mission_chat.lean_operative_rules`` (root config, default
  OFF) serves the deduped rules; the threading bullets live in
  ``agent_chat_send``'s describe doc.
* S6 — the cache scope is the persona INSTANCE (ruling R5): two chats of one
  instance route to one bucket, two instances never share one.

The prewarm and its first turn derive both S3 and S6 values through the same
helpers, so they agree; the end-to-end check rides the real prewarm assembly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.cache_routing import apply_persona_cache_routing, persona_cache_scope_id
from agent_runtime.chat_lane_skill_index import (
    COMPACT_ATTR,
    apply_chat_lane_skill_scope,
    chat_lane_index_skills,
    compact_skill_categories,
)
from agent_runtime.mission_chat_prompts import LEAN_OPERATIVE_RULES, _mission_chat_operative_rules
from agent_runtime.persona_runtime import GPTPersonaRuntime
from agent_runtime.profile_runner import AgentRunResult
from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.persona_samples import sample_personas

# ── S3 ──────────────────────────────────────────────────────────────────────


def _skill(root, rel: str, name: str) -> None:
    path = root / rel / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: d\n---\n", encoding="utf-8")


def test_compact_categories_are_every_top_category_without_a_kept_skill(tmp_path):
    root = tmp_path / "skills"
    _skill(root, "software-development/plans", "plans")
    _skill(root, "software-development/nested/deep", "deep")
    _skill(root, "creative/comic", "comic")
    _skill(root, "mission-lead", "harness-mission-lead")  # frontmatter name differs from the dir

    demote = compact_skill_categories(["plans", "harness-mission-lead"], roots=[root])

    assert demote == frozenset({"creative"})


def test_a_persona_with_no_declared_skills_is_not_scoped():
    assert chat_lane_index_skills(SimpleNamespace(skills=[]), ["launcher-mcp-operations"]) is None
    assert chat_lane_index_skills(SimpleNamespace(skills=["b", "a"]), ["c", "a"]) == ("a", "b", "c")


def test_apply_stamps_the_attribute_and_none_leaves_the_agent_alone(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _skill(root, "creative/comic", "comic")
    _skill(root, "dev/plans", "plans")
    monkeypatch.setattr("agent.skill_utils.get_all_skills_dirs", lambda: [root])

    scoped, unscoped = SimpleNamespace(), SimpleNamespace()
    apply_chat_lane_skill_scope(scoped, ("plans",))
    apply_chat_lane_skill_scope(unscoped, None)

    assert getattr(scoped, COMPACT_ATTR) == frozenset({"creative"})
    assert not hasattr(unscoped, COMPACT_ATTR)


# ── S6 ──────────────────────────────────────────────────────────────────────


def test_the_scope_is_the_instance_and_falls_back_to_the_chat():
    assert persona_cache_scope_id("personainst_neko_1", "chat-a") == "persona_chat:personainst_neko_1"
    assert persona_cache_scope_id(None, "chat-a") == "chat-a"
    assert persona_cache_scope_id("  ", "chat-a") == "chat-a"


def _turn_request(persona, *, instance_id: str, chat: str):
    captured = {}

    class CapturingRunner:
        def run(self, request):
            captured["request"] = request
            return AgentRunResult(final_response="ok", session_id=chat, provider="openai-codex",
                                  model="gpt-5.5", base_url=None, messages=[])

    GPTPersonaRuntime(
        default_provider="openai-codex", default_model="gpt-5.5", agent_runner=CapturingRunner()
    ).mission_chat_reply(persona, "hi", session_id=None, permission_session_id=chat,
                         turn_id=f"turn-{chat}", persona_instance_id=instance_id)
    return captured["request"]


def _headers(scope):
    request = {"instructions": "same prefix", "tools": [{"type": "function", "name": "t"}],
               "prompt_cache_key": "x"}
    _, observability = apply_persona_cache_routing(
        request, cache_scope_id=scope, session_id=None, is_codex_backend=True,
        is_github_responses=False, is_xai_responses=False,
    )
    return observability


def test_two_chats_of_one_instance_share_a_bucket_and_two_instances_never_do(tmp_path, monkeypatch):
    """Positive control (CHANGE commit): plant ``cache_scope_id=perm_session_id`` back in
    ``persona_runtime.mission_chat_reply`` -> the first assertion reds."""

    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    neko = next(p for p in sample_personas() if p.id == "neko_supervisor")

    first = _turn_request(neko, instance_id="personainst_neko_1", chat="chat-1")
    second = _turn_request(neko, instance_id="personainst_neko_1", chat="chat-2")
    other = _turn_request(neko, instance_id="personainst_other_1", chat="chat-3")

    assert first.cache_scope_id == second.cache_scope_id == "persona_chat:personainst_neko_1"
    assert other.cache_scope_id != first.cache_scope_id
    one, two, three = (_headers(r.cache_scope_id) for r in (first, second, other))
    assert one["session_header_fingerprint"] == two["session_header_fingerprint"]
    assert one["session_header_fingerprint"] != three["session_header_fingerprint"]
    # The body key is content-addressed either way; the scope never enters it.
    assert one["prompt_cache_key_fingerprint"] == three["prompt_cache_key_fingerprint"]


def test_the_turn_carries_the_persona_index_skills():
    neko = next(p for p in sample_personas() if p.id == "neko_supervisor")
    request = _turn_request(neko, instance_id="personainst_neko_1", chat="chat-1")
    assert request.chat_lane_index_skills == chat_lane_index_skills(neko, ())


def test_the_prewarm_and_its_first_turn_agree(persisted_persona_samples, bundled_persona_profiles, monkeypatch):
    """The real prewarm assembly derives the scope, the index skills and the system
    message through the turn's own helpers — flag off and flag on."""

    from agent_runtime import persona_chat_actor_prewarm as prewarm_module
    from agent_runtime.chat_lane_bundle import chat_lane_bundle
    from agent_runtime.config import load_agent_runtime_config
    from agent_runtime.models import apply_instance_model_overrides
    from agent_runtime.persona_runtime import _mission_chat_surface_message
    from hermes_cli.harness_parts.persona.chat_target import _persona_by_id
    from tests.agent_runtime.test_persona_chat_actor_prewarm import _live_chat_root

    root, instance, _db = _live_chat_root()
    persona = apply_instance_model_overrides(_persona_by_id(load_agent_runtime_config(), "dev"), instance)
    for lean in (False, True):
        monkeypatch.setattr("agent_runtime.config.mission_chat_lean_operative_rules", lambda lean=lean: lean)
        request, _runner = prewarm_module._prepare(root, None)
        assert request.cache_scope_id == persona_cache_scope_id(instance.id, root)
        assert request.cache_scope_id.startswith("persona_chat:")
        operating = chat_lane_bundle(persona, session_id=root).operating_skills
        assert request.chat_lane_index_skills == chat_lane_index_skills(persona, operating)
        assert request.system_message == _mission_chat_surface_message(
            persona, "", workspace_agents_content=prewarm_module._workspace_agents_content(instance)
        )
        assert (LEAN_OPERATIVE_RULES in request.system_message) is lean


# ── S4 ──────────────────────────────────────────────────────────────────────

#: The lean rules' ceiling (plan S4). Killing mutation (run, see the CHANGE commit):
#: paste the retired "Never fabricate" bullet back -> the retired-text assertion reds.
LEAN_RULES_MAX_CHARS = 4000


@pytest.fixture
def root_config(tmp_path, monkeypatch):
    from agent_runtime import config as cfgpkg

    path = tmp_path / "config.yaml"
    patch_where_bound(monkeypatch, cfgpkg, "harness_root_config_path", lambda: path)
    return path


def test_the_flag_is_off_by_default_and_off_is_todays_text(root_config):
    root_config.write_text("agent_runtime:\n  mission_chat: {}\n", encoding="utf-8")
    full = _mission_chat_operative_rules()
    assert full != LEAN_OPERATIVE_RULES
    assert "clarify_token" in full and "Never fabricate" in full and "ambiguous_target" in full


@pytest.mark.parametrize("raw", ["true", "'true'", "1"])
def test_only_a_yaml_true_turns_it_on(root_config, raw):
    root_config.write_text(f"agent_runtime:\n  mission_chat:\n    lean_operative_rules: {raw}\n", encoding="utf-8")
    assert (_mission_chat_operative_rules() == LEAN_OPERATIVE_RULES) is (raw == "true")


def test_the_lean_rules_keep_the_channel_rules_and_drop_the_foundations(root_config):
    root_config.write_text("agent_runtime:\n  mission_chat:\n    lean_operative_rules: true\n", encoding="utf-8")
    lean = _mission_chat_operative_rules()
    assert len(lean) <= LEAN_RULES_MAX_CHARS
    for kept in ("HARD RULE", "`clarify` does NOT block", "unbounded", "DELEGATION", "MEDIA:", "chat-only"):
        assert kept in lean, kept
    for retired in ("Never fabricate", "You have real tools", "clarify_token` that came inside",
                    "`new_session: false`", "ambiguous_target"):
        assert retired not in lean, retired


def test_the_threading_bullets_live_in_agent_chat_sends_describe_doc():
    from tools.tool_full_descriptions import full_tool_description

    doc = full_tool_description("agent_chat_send")
    for moved in ("clarify_token", "clarify_request", "ambiguous_target", "@personainst_*", "agent_chat_threads"):
        assert moved in doc, moved
