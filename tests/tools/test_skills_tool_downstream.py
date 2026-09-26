"""Fork-owned tests moved out of ``tests/tools/test_skills_tool.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import json
from unittest.mock import patch
import tools.skills_tool as skills_tool_module
from agent_runtime.skill_search import skill_search
from tools.skills_tool import (
    skills_list,
    skill_view,
)

from tests.tools.test_skills_tool import (  # noqa: F401 — upstream names the moved tests use
    _make_skill,
)


class TestSkillView:
    # Fork-owned: mission-surface / root-node gating via skill_runtime_scope has
    # no upstream counterpart. Re-homed here after upstream rewrote the
    # resolve-by-dir-name case above.
    def test_view_rejects_root_node_only_skill_in_mission_chat(self, tmp_path):
        from agent_runtime.skill_resolution import skill_runtime_scope
        from agent_runtime.skill_view_result import transform_skill_view_result

        with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
            _make_skill(
                tmp_path,
                "root-only",
                frontmatter_extra=(
                    "metadata:\n  hermes:\n    surfaces: [mission_worker]\n"
                    "    modes: [root_node]\n"
                ),
            )
            with skill_runtime_scope(surface="mission_chat", root_node_mode=False):
                raw = skill_view("root-only")
                refused = transform_skill_view_result(
                    tool_name="skill_view", args={"name": "root-only"}, result=raw)

        # Lane PF-3: the refusal is the plugin's transform_tool_result hook, so it holds on
        # the MODEL path; a direct in-process caller is served (plugin-fit §4 Q3).
        assert json.loads(raw)["success"] is True
        result = json.loads(refused)
        assert result["success"] is False
        assert result["reason"] == "surface_not_supported"

    def test_mission_chat_cannot_list_root_node_only_skill(self, tmp_path):
        from agent_runtime.skill_resolution import skill_runtime_scope

        with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
            _make_skill(
                tmp_path,
                "root-only",
                frontmatter_extra=(
                    "metadata:\n  hermes:\n    surfaces: [mission_worker]\n"
                    "    modes: [root_node]\n"
                ),
            )
            _make_skill(tmp_path, "general-skill")
            with skill_runtime_scope(surface="mission_chat", root_node_mode=False):
                raw = skills_list()

        result = json.loads(raw)
        assert [skill["name"] for skill in result["skills"]] == ["general-skill"]


# Fork-owned: `skill_search` is a fork tool with no upstream counterpart.
class TestSkillSearch:
    def test_search_installed_skills_returns_compact_matches(self, tmp_path):
        _make_skill(
            tmp_path,
            "flutter-ui-development",
            category="software-development",
            body="FULL BODY SHOULD NOT LEAK INTO SEARCH RESULTS",
        )
        _make_skill(tmp_path, "spotify", category="media")

        with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
            raw = skill_search("flutter", source="installed", limit=10)

        result = json.loads(raw)
        assert result["success"] is True
        assert result["query"] == "flutter"
        assert result["count"] == 1
        assert result["results"] == [
            {
                "name": "flutter-ui-development",
                "identifier": "software-development/flutter-ui-development",
                "source": "installed",
                "description": "Description for flutter-ui-development.",
                "installed": True,
                "category": "software-development",
                "tags": [],
            }
        ]
        assert "FULL BODY SHOULD NOT LEAK" not in raw

    def test_search_validates_empty_query(self):
        result = json.loads(skill_search("   "))

        assert result["success"] is False
        assert "query" in result["error"]

    def test_search_installed_nested_skill_identifier_loads_with_skill_view(self, tmp_path):
        _make_skill(
            tmp_path,
            "deep-skill",
            category="foundations/runtime",
            body="Nested skill body.",
        )

        with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
            search_result = json.loads(skill_search("deep", source="installed"))
            identifier = search_result["results"][0]["identifier"]
            view_result = json.loads(skill_view(identifier))

        assert identifier == "foundations/runtime/deep-skill"
        assert view_result["success"] is True
        assert "Nested skill body." in view_result["content"]

    def test_search_caps_limit_and_preserves_installed_first(self, tmp_path):
        _make_skill(tmp_path, "alpha-local", body="No body in search")

        with patch("tools.skills_tool.SKILLS_DIR", tmp_path), \
             patch("agent_runtime.skill_search.unified_search") as unified, \
             patch("agent_runtime.skill_search.create_source_router", return_value=[]):
            from tools.skills_hub_models import SkillMeta

            unified.return_value = [
                SkillMeta(
                    name="alpha-remote",
                    description="Remote alpha skill.",
                    source="hermes-index",
                    identifier="owner/repo/alpha-remote",
                    trust_level="community",
                    tags=["alpha"],
                )
            ]
            raw = skill_search("alpha", source="all", limit=99)

        result = json.loads(raw)
        assert result["success"] is True
        assert result["limit"] == 50
        assert [item["source"] for item in result["results"]] == [
            "installed",
            "hermes-index",
        ]
        assert result["results"][0]["identifier"] == "alpha-local"
        assert result["results"][1]["installed"] is False
        assert "trust_level" in result["results"][1]

    def test_tool_is_registered_under_skills_toolset(self):
        """The harness plugin registers it (seam Stage 2), into the built-in ``skills`` toolset."""
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
        entry = skills_tool_module.registry.get_entry("skill_search")

        assert entry is not None
        assert entry.toolset == "skills"
        assert entry.schema["name"] == "skill_search"
        assert "query" in entry.schema["parameters"]["required"]

    def test_skill_search_exposed_on_default_hermes_cli_session(self):
        """Regression: registering ``skill_search`` under the ``skills`` toolset
        is not enough — the default interactive session resolves its schema
        footprint from the ``hermes-cli`` platform bundle. If ``skill_search``
        isn't wired into that composition, ``get_tool_definitions`` never sends
        the schema to the model and the tool is silently unreachable by default.
        """
        from hermes_cli.plugins import discover_plugins
        from model_tools import get_tool_definitions, _clear_tool_defs_cache

        discover_plugins()  # agent init does this before the tool snapshot (skill_search is a plugin tool)
        _clear_tool_defs_cache()
        tools = get_tool_definitions(enabled_toolsets=["hermes-cli"], quiet_mode=True)
        names = {t.get("function", {}).get("name") for t in tools}

        assert "skill_search" in names, (
            "skill_search must be exposed on the default hermes-cli session path "
            "(wire it into _HERMES_CORE_TOOLS in toolsets.py)"
        )
        # The exposed schema must be the real one the model can call.
        schema = next(
            t["function"] for t in tools
            if t.get("function", {}).get("name") == "skill_search"
        )
        assert "query" in schema["parameters"]["required"]

    def test_skill_search_travels_with_skills_list_on_default_path(self):
        """Discovery-tool parity guard: any default session that can enumerate
        skills (``skills_list``) must also be able to search them
        (``skill_search``). This fails loudly if a future edit exposes one
        without the other."""
        from hermes_cli.plugins import discover_plugins
        from model_tools import get_tool_definitions, _clear_tool_defs_cache

        discover_plugins()  # agent init does this before the tool snapshot (skill_search is a plugin tool)
        _clear_tool_defs_cache()
        tools = get_tool_definitions(enabled_toolsets=["hermes-cli"], quiet_mode=True)
        names = {t.get("function", {}).get("name") for t in tools}

        assert {"skills_list", "skill_view", "skill_search"} <= names
