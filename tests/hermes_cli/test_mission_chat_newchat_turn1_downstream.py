"""A new chat's turn 1 builds no chat-lane bundle on the turn path (lane h-newchat-t1).

Live 2026-10-06 01:25 (local), Neko's new chat, turn ``5377d205``: ``rt_bundle_builds=2`` with
``visibility_bundle_rebuild_component_registry_content=1``. The chat-open prewarm had built the
root's bundle; its construction then admitted ``launcher_qa`` (36 ``mcp-*`` tools registered,
torn down at the end) while the turn was assembling, and the bundle key read those registrations
-- one rebuild as the scope came up, one as it went down. Another run's admission scope is not
this chat's content; the key leaves ``mcp-*`` registrations out.

Driven through the REAL handler (``_cmd_mission_chat_message``), with the bundle warmed off the
turn's thread the way the prewarm warms it.
"""

from __future__ import annotations

import threading

from agent_runtime.config import AgentRuntimeConfig
from agent_runtime.mission_chat_phases import TURN_PHASES_KEY
from agent_runtime.mission_chat_turns import TURN_PROFILE_TIMING_KEY

from tests.hermes_cli.test_mission_chat_turn_phases import (  # type: ignore
    _SESSION_ID,
    _drive,
    _record_on_disk,
    _streaming_provider,
    isolate_agent_runtime_root,  # noqa: F401  (re-exported fixture)
    scripted_marks,  # noqa: F401  (re-exported fixture)
)
from tests.hermes_cli.test_mission_chat_budget_payload import _seed  # type: ignore
from hermes_cli.harness_parts.persona import chat_turn_message


def _prewarm_the_bundle(monkeypatch) -> None:
    """What ``persona_chat_actor_prewarm._prepare`` does for the opened root: resolve the
    lane bundle on its own thread, before the operator's first message."""

    import model_tools  # noqa: F401  -- registers the builtins, as the serve's boot does
    from agent_runtime.chat_lane_bundle import chat_lane_bundle
    from agent_runtime.tool_visibility import _ensure_plugin_tools_registered

    _seed(monkeypatch, _streaming_provider())
    _ensure_plugin_tools_registered()  # the serve discovered its plugins long before the open
    persona = chat_turn_message._persona_by_id(AgentRuntimeConfig(), "dev")
    worker = threading.Thread(target=lambda: chat_lane_bundle(persona, session_id=_SESSION_ID))
    worker.start()
    worker.join(30)


def _admission_scope(name: str):
    from tools.registry import registry

    registry.register(
        name=name,
        toolset="mcp-newchat-prewarm",
        schema={"name": name, "description": "x", "parameters": {"type": "object", "properties": {}}},
        handler=lambda args, **_kw: "ok",
    )
    registry.register_toolset_alias("newchat-prewarm", "mcp-newchat-prewarm")
    return lambda: registry.deregister(name)


def _builds_and_moves(root, turn_id):
    record = _record_on_disk(root, turn_id)
    moved = sorted(k for k in record[TURN_PROFILE_TIMING_KEY]
                   if k.startswith("visibility_bundle_rebuild_component_"))
    return record[TURN_PHASES_KEY].get("visibility_bundle_builds"), moved


def test_a_prewarmed_new_chat_turn_one_builds_no_bundle(
    monkeypatch, capsys, isolate_agent_runtime_root, scripted_marks  # noqa: F811
):
    """The baseline the live 00:15 chat read (``rt_bundle_builds=0``): prewarm, then turn 1."""

    _prewarm_the_bundle(monkeypatch)
    _drive(monkeypatch, capsys, _streaming_provider(profile_timing={"resident_actor_reused": 1}),
           turn_id="newchat_t1_quiet")
    assert _builds_and_moves(isolate_agent_runtime_root, "newchat_t1_quiet") == (0, [])


def test_another_runs_admission_during_turn_one_builds_no_bundle(
    monkeypatch, capsys, isolate_agent_runtime_root, scripted_marks  # noqa: F811
):
    """The 01:25 case: the prewarm's admission scope is live while turn 1 assembles.

    *Killing mutation:* key ``registry_content`` on every ``(tool, toolset)`` pair again --
    turn 1 records ``visibility_bundle_builds=1`` and names ``registry_content``.
    """

    _prewarm_the_bundle(monkeypatch)
    teardown = _admission_scope("mcp_newchat_prewarm_echo")
    try:
        _drive(monkeypatch, capsys, _streaming_provider(profile_timing={"resident_actor_reused": 1}),
               turn_id="newchat_t1_overlap")
    finally:
        teardown()
    assert _builds_and_moves(isolate_agent_runtime_root, "newchat_t1_overlap") == (0, [])
