"""The harness's ``skill_view`` result transform (plugin-fit PF-3, ``transform_tool_result``)."""

from __future__ import annotations

import json
from unittest.mock import patch

from agent_runtime.skill_resolution import skill_runtime_scope
from agent_runtime.skill_view_result import transform_skill_view_result
from tests.tools.test_skills_tool import _make_skill

_ROOT_ONLY = "metadata:\n  hermes:\n    surfaces: [mission_worker]\n    modes: [root_node]\n"


def _view(tmp_path, name, scope=None, **args):
    """What the model gets: ``skill_view`` served unscoped (what a direct call returns
    outside a lane), then the transform under ``scope`` — the ordering the hook runs in."""
    from tools.skills_tool import skill_view

    with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
        raw = skill_view(name, file_path=args.get("file_path"))
        with skill_runtime_scope(**(scope or {"surface": None})):
            return raw, transform_skill_view_result(tool_name="skill_view", args={"name": name, **args}, result=raw)


_STAMPS = ("resolution_status", "source_kind", "content_hash")


def test_an_incompatible_skill_is_refused_on_the_model_path(tmp_path):
    _make_skill(tmp_path, "root-only", frontmatter_extra=_ROOT_ONLY)
    _raw, out = _view(tmp_path, "root-only", scope={"surface": "mission_chat"})
    refused = json.loads(out)
    assert refused["success"] is False
    assert refused["reason"] == "surface_not_supported"
    assert refused["readiness_status"] == "unsupported"
    assert refused["mode"] == "standard"


def test_the_same_skill_on_its_own_surface_is_served_and_stamped(tmp_path):
    """Positive control for the refusal above: same bytes, the surface it declares."""
    _make_skill(tmp_path, "root-only", frontmatter_extra=_ROOT_ONLY)
    raw, out = _view(tmp_path, "root-only", scope={"surface": "mission_worker", "root_node_mode": True})
    served = json.loads(out)
    assert served["success"] is True
    assert served["resolution_status"] == "resolved"
    assert len(served["content_hash"]) == 64
    assert served["source_kind"] == "external"
    assert list(served)[:3] == list(_STAMPS)
    unstamped = {k: v for k, v in json.loads(raw).items() if k not in _STAMPS}
    assert {k: v for k, v in served.items() if k not in _STAMPS} == unstamped


def test_a_linked_file_of_an_incompatible_skill_is_refused(tmp_path):
    skill_dir = _make_skill(tmp_path, "root-only", frontmatter_extra=_ROOT_ONLY)
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "api.md").write_text("# api\n")
    _raw, out = _view(tmp_path, "root-only", scope={"surface": "mission_chat"}, file_path="references/api.md")
    assert json.loads(out)["reason"] == "surface_not_supported"


def test_outside_a_lane_nothing_is_refused_and_linked_files_are_left_alone(tmp_path):
    skill_dir = _make_skill(tmp_path, "root-only", frontmatter_extra=_ROOT_ONLY)
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "api.md").write_text("# api\n")
    _raw, out = _view(tmp_path, "root-only")
    assert json.loads(out)["success"] is True
    _raw, out = _view(tmp_path, "root-only", file_path="references/api.md")
    assert out is None


def test_other_tools_and_failures_pass_through():
    assert transform_skill_view_result(tool_name="read_file", args={}, result='{"success": true}') is None
    assert transform_skill_view_result(tool_name="skill_view", args={}, result='{"success": false}') is None
    assert transform_skill_view_result(tool_name="skill_view", args={}, result="not json") is None


def test_a_plugin_skill_is_refused_through_the_plugin_registry(tmp_path):
    skill_dir = _make_skill(tmp_path, "writing", frontmatter_extra=_ROOT_ONLY)

    class _Manager:
        def find_plugin_skill(self, name):
            return skill_dir / "SKILL.md" if name == "demo:writing" else None

    result = json.dumps({"success": True, "name": "demo:writing", "content": "x"})
    with patch("hermes_cli.plugins.get_plugin_manager", return_value=_Manager()):
        with skill_runtime_scope(surface="mission_chat"):
            out = transform_skill_view_result(tool_name="skill_view", args={"name": "demo:writing"}, result=result)
        assert json.loads(out)["reason"] == "surface_not_supported"
        with skill_runtime_scope(surface="mission_worker", root_node_mode=True):
            assert transform_skill_view_result(
                tool_name="skill_view", args={"name": "demo:writing"}, result=result) is None


def test_the_plugin_hook_refuses_on_the_model_dispatch_path(tmp_path, monkeypatch):
    """End to end: ``model_tools.handle_function_call`` -> the plugin's registered
    ``transform_tool_result`` callback. Positive control: the declared surface serves."""
    import model_tools
    from tests.agent_runtime.test_codex_stream_receipt import _plugin_hooks

    _plugin, hooks = _plugin_hooks()
    monkeypatch.setattr("hermes_cli.plugins.has_hook", lambda name: name in hooks)
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook",
                        lambda name, **kw: [cb(**kw) for cb in hooks.get(name, ())])
    _make_skill(tmp_path, "root-only", frontmatter_extra=_ROOT_ONLY)

    def _call(**scope):  # a task per call: the repeat-view dedup would stub the second one
        with patch("tools.skills_tool.SKILLS_DIR", tmp_path), skill_runtime_scope(**scope):
            return json.loads(model_tools.handle_function_call(
                "skill_view", {"name": "root-only"}, task_id=f"t-{scope['surface']}", session_id="s-pf3",
                tool_call_id="tc1", skip_pre_tool_call_hook=True))

    assert _call(surface="mission_chat")["reason"] == "surface_not_supported"
    served = _call(surface="mission_worker", root_node_mode=True)
    assert served["success"] is True and len(served["content_hash"]) == 64


def test_a_direct_caller_in_a_lane_is_served(tmp_path):
    """plugin-fit §4 Q3, recorded: after lane PF-3 skill_view itself no longer refuses,
    so an in-process caller inside a lane gets the skill; only the model path is gated."""
    from tools.skills_tool import skill_view

    _make_skill(tmp_path, "root-only", frontmatter_extra=_ROOT_ONLY)
    with patch("tools.skills_tool.SKILLS_DIR", tmp_path), skill_runtime_scope(surface="mission_chat"):
        served = json.loads(skill_view("root-only"))
    assert served["success"] is True
    assert not set(_STAMPS) & set(served)
