"""S1 of the mission-lane removal — the protective stage.

Nothing in S1 deletes a feature; every item relocates, extracts, or de-gates
something so the KEEP set survives the deletions in S3-S12. These tests pin the
contracts those later stages will lean on:

1. (retired: the ``TaskStore`` stub, deleted with RT-TASK-STORE-STUB-FATE once
   ``tools/board_tool.py`` stopped importing it),
2. ``promote_profile_to_persona`` at its new home in ``agent_runtime.persona_profiles``,
   still reachable from the upstream import path.

Items 3-5 were the Stage C Python capture extractions, retired in S14 by operator
ruling — see the note below. Item 6 (``_augment_chat_capabilities`` appending
unconditionally) is pinned in ``test_board_agent_tools.py``, next to the board
toolset gating it protects.
"""

from __future__ import annotations



from agent_runtime import paths


# ── item 2: promote_profile_to_persona re-homed ───────────────────────────


def test_promote_profile_to_persona_lives_in_persona_profiles():
    from agent_runtime.persona_profiles import promote_profile_to_persona

    assert promote_profile_to_persona.__module__ == "agent_runtime.persona_profiles"


def test_upstream_import_path_still_resolves_to_the_same_function():
    """``hermes_cli/web_server.py`` is upstream-owned and cannot be edited.

    It does ``from agent_runtime.blueprints.resolve import promote_profile_to_persona``
    to back ``POST /api/profiles/{name}/promote``, so that path must keep resolving
    to the one real implementation.
    """

    from agent_runtime.blueprints.resolve import promote_profile_to_persona as via_blueprints
    from agent_runtime.persona_profiles import promote_profile_to_persona as via_personas

    assert via_blueprints is via_personas


def test_promotion_clones_the_role_template_and_binds_the_profile():
    from agent_runtime.models import AgentPersona
    from agent_runtime.persona_profiles import promote_profile_to_persona
    from agent_runtime.store import AgentStore

    template = AgentPersona(
        id="qa",
        display_name="QA Agent",
        role="qa",
        model="m",
        provider="p",
        api_mode="chat",
        system_prompt_path="agent_runtime/prompts/qa.md",
    )
    store = AgentStore()
    store.save(template)

    persona = promote_profile_to_persona(
        "launcher-qa", slot_role="verifier", personas={"qa": template}, agent_store=store
    )
    # `verifier` maps to the `qa` template via the re-homed _ROLE_TEMPLATE.
    assert persona.id == "launcher-qa"
    assert persona.hermes_profile == "launcher-qa"
    assert persona.role == "qa"
    assert persona.system_prompt_path == "agent_runtime/prompts/qa.md"
    assert store.get("launcher-qa").hermes_profile == "launcher-qa"


def test_promotion_unknown_role_does_not_clone_an_unrelated_stored_persona():
    from agent_runtime.models import AgentPersona
    from agent_runtime.persona_profiles import promote_profile_to_persona
    from agent_runtime.store import AgentStore

    store = AgentStore()
    store.save(
        AgentPersona(
            id="qa",
            display_name="QA Agent",
            role="qa",
            model="qa-model",
            provider="qa-provider",
            api_mode="chat",
            system_prompt_path="agent_runtime/prompts/qa.md",
        )
    )

    persona = promote_profile_to_persona(
        "fresh-builder", slot_role="builder", agent_store=store
    )

    assert persona.role == "builder"
    assert persona.hermes_profile == "fresh-builder"
    assert persona.model != "qa-model"


# ── items 3-5: the Stage C Python capture lane (retired in S14) ───────────
#
# S1 extracted the Stage C command-argument checks, the trace parsers, and the
# rebuild-artifact path so a *Python* capture lane could survive S3-S12. The
# 2026-07-30 operator ruling retired that lane outright: Stage C visual proof lives
# only as the ``launcher_qa`` MCP server plus the marionette skill. Those three
# items therefore have nothing left to protect and their tests went with
# ``agent_runtime/stagec_command_policy.py``, ``stagec_trace_parsers.py``,
# ``proof_capture.py``, and ``stagec_mcp_visual_provider.py``.
# The removal itself is pinned in ``test_s14_stagec_python_capture_removal.py`` (deleted 2026-09-24).




def test_no_proofs_store_is_created_by_the_runtime():
    """The ``proofs/`` store S1 repointed away from must never come back."""

    assert not (paths.store_root() / "proofs").exists()
