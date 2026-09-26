"""Fork-owned tests moved out of ``tests/tools/test_toolsets.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from toolsets import (
    TOOLSETS,
    resolve_toolset,
)


class TestSkillSearchToolsetCoverage:
    """``skill_search`` must resolve into every platform bundle that ships the
    skill-discovery tools, so normal agents receive its schema by default.

    See the sibling ``get_tool_definitions(enabled_toolsets=["hermes-cli"])``
    regression in ``tests/tools/test_skills_tool.py`` for the end-to-end
    (schema-resolution + check_fn) proof on the default session path.
    """

    def test_hermes_cli_toolset_includes_skill_search(self):
        assert "skill_search" in resolve_toolset("hermes-cli")

    def test_messaging_platforms_include_skill_search(self):
        for platform in (
            "hermes-cron",
            "hermes-telegram",
            "hermes-discord",
            "hermes-whatsapp",
            "hermes-slack",
            "hermes-signal",
            "hermes-api-server",
            "hermes-acp",
        ):
            assert "skill_search" in resolve_toolset(platform), (
                f"{platform} exposes skill discovery but is missing skill_search"
            )

    def test_standalone_skills_toolset_includes_skill_search(self):
        assert "skill_search" in resolve_toolset("skills")

    def test_skill_search_travels_with_skills_list_across_all_toolsets(self):
        """Parity invariant: no toolset may expose ``skills_list`` without also
        exposing ``skill_search``. Guards against a future toolset (or a new
        platform bundle) enumerating skills while leaving search unreachable."""
        for name in TOOLSETS:
            resolved = set(resolve_toolset(name))
            if "skills_list" in resolved:
                assert "skill_search" in resolved, (
                    f"toolset '{name}' exposes skills_list without skill_search"
                )


class TestHarnessCoreToolset:
    """``harness_core`` — the ONE toolset an Eternia persona profile declares.

    S0a A1 (2026-09-03), plan
    ``docs/agent-runtime-harness/archive/s0a-atlas-cleanup.md``. The numbers here
    are the ratchet's static twin: what the harness lane admits, in tool NAMES,
    resolved from this file alone.
    """

    def test_harness_core_retains_required_capabilities_with_the_registry(self):
        from tools.registry import discover_builtin_tools

        discover_builtin_tools()  # populates agent_chat / board / browser-cdp

        resolved = set(resolve_toolset("harness_core"))

        # Membership grows through declared included toolsets; pin capabilities,
        # not an obsolete inventory count that rejects legitimate upstream additions.
        # The fork's own two lanes are IN — they are registry-only toolsets, so
        # this is also the proof that an ``includes`` reaches the registry view.
        assert {"agent_chat_send", "agent_chat_threads", "board_card_add"} <= resolved
        # ... and the conversational core the manual routes agents to.
        assert {"clarify", "delegate_task", "terminal", "read_file", "web_search"} <= resolved
        # ``browser-cdp`` is named as its own member so the two resolution
        # lenses agree (43 at S0a, 44 since S2b; see the comment in TOOLSETS).
        assert {"browser_cdp", "browser_dialog"} <= resolved

    def test_harness_core_never_resolves_a_registry_hygiene_name(self):
        """The static twin of the emitter's refusal: an inventory that lists a
        withheld tool is worse than no inventory."""

        from agent_runtime.personas import REGISTRY_HYGIENE_BLOCKED_TOOLS
        from tools.registry import discover_builtin_tools

        discover_builtin_tools()

        assert not (set(resolve_toolset("harness_core")) & REGISTRY_HYGIENE_BLOCKED_TOOLS)

    def test_harness_core_static_view_drops_only_the_registry_only_members(self):
        static = set(resolve_toolset("harness_core", include_registry=False))

        assert "agent_chat_send" not in static
        assert "board_card_add" not in static
        assert {"terminal", "read_file", "clarify", "delegate_task"} <= static

    def test_expand_toolset_names_returns_the_member_names_in_order(self):
        from agent_runtime.toolset_names import expand_toolset_names

        assert expand_toolset_names(["harness_core"]) == [
            "agent_chat", "board", "clarify", "delegation", "terminal", "file",
            "web", "browser", "browser-cdp", "skills", "memory", "todo",
            "session_search", "vision", "code_execution",
        ]

    def test_expand_toolset_names_passes_leaves_and_unknowns_through(self):
        from agent_runtime.toolset_names import expand_toolset_names

        assert expand_toolset_names(["file", "mcp-launcher_qa", "made_up"]) == [
            "file", "mcp-launcher_qa", "made_up",
        ]
        # Order-preserving and deduped across a bundle and its own members.
        assert expand_toolset_names(["file", "harness_core", "file"])[:2] == [
            "file", "agent_chat",
        ]

    def test_expand_toolset_names_does_not_expand_a_composite_that_owns_tools(self):
        """``debugging`` has ``includes`` AND direct tools: expanding it to its
        members would silently drop ``terminal``/``process``. It passes through."""

        from agent_runtime.toolset_names import expand_toolset_names

        assert expand_toolset_names(["debugging"]) == ["debugging"]

    def test_expand_toolset_names_reads_no_registry(self):
        """The A6a property, in-process: names without the registrars."""

        import subprocess
        import sys

        code = (
            "import sys\n"
            "from agent_runtime.toolset_names import expand_toolset_names\n"
            "names = expand_toolset_names(['harness_core'])\n"
            "assert len(names) == 15, names\n"
            "print('model_tools' in sys.modules)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert out.stdout.strip() == "False", out.stdout
