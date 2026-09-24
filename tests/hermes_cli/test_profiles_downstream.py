"""Fork-owned tests moved out of ``tests/hermes_cli/test_profiles.py`` (lane CARRY2A).

Same names, same bodies; the upstream file is byte-identical to upstream. The
upstream ``profile_env`` fixture is imported by name.
"""

from unittest.mock import patch

from hermes_cli.profiles import (
    create_profile,
    delete_profile,
)
from tests.hermes_cli.test_profiles import profile_env  # noqa: F401 — upstream fixture


class TestDeleteProfile:

    # Fork-owned (doc 17): profile deletion is NOT blocked by an agent-runtime
    # persona binding — the retired task-graph guard is gone, and the persona is
    # tombstoned as orphaned instead. Upstream has no agent_runtime, so these two
    # have no upstream counterpart and must survive the sync.
    def test_delete_is_not_blocked_by_retired_task_graph_binding(self, profile_env, tmp_path, monkeypatch):
        profile_dir = create_profile("coder", no_alias=True)
        monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))

        from agent_runtime.models import AgentPersona
        from agent_runtime.store import AgentStore

        AgentStore().save(
            AgentPersona(
                id="coder_persona",
                display_name="Coder",
                role="dev",
                model=None,
                provider=None,
                api_mode=None,
                toolsets=[],
                system_prompt_path="personas/dev/system.md",
                hermes_profile="coder",
            )
        )
        with patch("hermes_cli.profiles._cleanup_gateway_service"):
            delete_profile("coder", yes=True)
        assert not profile_dir.is_dir()

    def test_delete_marks_persisted_profile_persona_orphaned(self, profile_env, tmp_path, monkeypatch):
        profile_dir = create_profile("coder", no_alias=True)
        monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))

        from agent_runtime.models import AgentPersona
        from agent_runtime.store import AgentStore

        store = AgentStore()
        store.save(
            AgentPersona(
                id="coder_persona",
                display_name="Coder",
                role="dev",
                model=None,
                provider=None,
                api_mode=None,
                toolsets=[],
                system_prompt_path="personas/dev/system.md",
                hermes_profile="coder",
            )
        )

        with patch("hermes_cli.profiles._cleanup_gateway_service"):
            delete_profile("coder", yes=True)

        assert not profile_dir.is_dir()
        persona = store.get("coder_persona")
        assert persona.readiness["orphaned"] is True
