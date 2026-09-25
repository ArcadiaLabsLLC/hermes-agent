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

    def test_delete_unbacks_the_profiles_personas_through_upstreams_tombstone(
        self, profile_env, tmp_path, monkeypatch
    ):
        """Owner ruling 2026-09-24 (3): the harness reads upstream's delete tombstone; a
        persona bound to a deleted profile backs nothing, so its placements classify as
        ``orphan-no-profile`` for the reconcile/snapshot lanes to clear."""
        create_profile("coder", no_alias=True)
        create_profile("keeper", no_alias=True)
        monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))

        from agent_runtime.models import AgentPersona
        from agent_runtime.persona_instance_identity import backed_persona_identity
        from agent_runtime.store import AgentStore

        store = AgentStore()
        for pid, profile in (("coder_persona", "coder"), ("keeper_persona", "keeper")):
            store.save(
                AgentPersona(
                    id=pid, display_name=pid, role="dev", model=None, provider=None,
                    api_mode=None, toolsets=[], system_prompt_path="personas/dev/system.md",
                    hermes_profile=profile,
                )
            )

        with patch("hermes_cli.profiles._cleanup_gateway_service"):
            delete_profile("coder", yes=True)

        persona_ids, profile_names = backed_persona_identity(profile_names=[])
        assert "coder_persona" not in persona_ids and "coder" not in profile_names
        # Positive control: the same store, the live profile's persona stays backed.
        assert "keeper_persona" in persona_ids and "keeper" in profile_names
