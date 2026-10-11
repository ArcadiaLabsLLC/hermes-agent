"""The HUD's deferred line reads the SETTLED tool surface, never a preview (runtime-queue, 2026-10-09).

The capability account used to resolve the cost layer's split at bundle build from the PREVIEW
surface and memoize it with the bundle, so it never saw per-run MCP admission or the
constructor's extras (prompt record ``ctx_74748dd3f4f23190``: HUD 15, receipt 49). The account
now carries no surface at all; the turn joins the receipt the tool form's owner settled on the
actor this turn reuses (``chat_lane_tool_form.settled_surface_receipt``). No receipt yet ⇒ no
deferred line, and the turn still builds.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.persona_chat_continuity.runtime_registry import PersonaChatRuntimeRegistry
from agent_runtime.runtime_hud import CAPABILITY_HUD_KEY
from agent_runtime.tool_surface import AGENT_SURFACE_ATTR
from tests.agent_runtime.test_mission_chat_turn_context import _build

_RECEIPT = {
    "deferred": {"memory": {"reason": "persona_defer",
                            "restorable_via": "agent_runtime.personas.<persona>.chat_lane_defer_tools"}},
    "unavailable": {},
    # What the preview could never see: the run's admitted MCP tools.
    "mcp": {"deferred": {"mcp__launcher_qa__a": {"reason": "mcp_defer"},
                         "mcp__launcher_qa__b": {"reason": "mcp_defer"}}},
}
_LINE = "- 1 tool deferred (and 2 MCP tools), reachable through tool_search"


@pytest.fixture
def registry(monkeypatch):
    # The registry's own state, which every reader reaches (patching the package's
    # re-exported accessor would miss a module that bound it by import).
    from agent_runtime.persona_chat_continuity import runtime_registry

    reg = PersonaChatRuntimeRegistry()
    monkeypatch.setattr(runtime_registry, "_REGISTRY", reg)
    return reg


def _resident(reg, *, root, signature, receipt):
    agent = SimpleNamespace(**{AGENT_SURFACE_ATTR: receipt})
    reg.acquire(root_session_id=root, active_session_id=root, signature=signature,
                revision="r", factory=lambda: agent)
    return agent


def test_the_turn_hud_reads_the_reused_actors_settled_receipt(registry):
    cold = _build()
    assert _LINE not in cold.volatile_tail.content, "no settled receipt yet: no deferred line"
    _resident(registry, root="chat-root-1", signature=cold.runtime_signature, receipt=_RECEIPT)

    warm = _build()

    assert warm.runtime_signature == cold.runtime_signature
    assert _LINE in warm.volatile_tail.content, warm.volatile_tail.content
    assert warm.capability["deferred"]["mcp_count"] == 2
    assert warm.situational_hud[CAPABILITY_HUD_KEY]["deferred"]["count"] == 1


def test_an_actor_the_turn_will_discard_is_not_described(registry):
    from agent_runtime.chat_lane_tool_form import settled_surface_receipt

    _resident(registry, root="chat-root-1", signature="sig-old", receipt=_RECEIPT)

    assert settled_surface_receipt("chat-root-1", signature="sig-new") is None
    # Positive control: the same entry under its own signature IS the reused actor.
    assert settled_surface_receipt("chat-root-1", signature="sig-old") is _RECEIPT


def test_a_not_computed_receipt_and_no_registry_cost_the_line_never_the_turn(registry, monkeypatch):
    from agent_runtime.chat_lane_tool_form import settled_surface_receipt
    from agent_runtime.persona_chat_continuity import runtime_registry

    _resident(registry, root="chat-root-1", signature="sig", receipt={"state": "not_computed"})
    assert settled_surface_receipt("chat-root-1", signature="sig") is None

    class _TornDown:
        def resident_agent(self, *_a, **_k):
            raise RuntimeError("registry torn down")

    monkeypatch.setattr(runtime_registry, "_REGISTRY", _TornDown())
    assert settled_surface_receipt("chat-root-1", signature="sig") is None
    context = _build()
    assert _LINE not in context.volatile_tail.content and context.volatile_tail.content


def test_the_peek_never_waits_on_another_roots_actor_build(registry):
    """``acquire`` holds the registry lock across ``factory()`` (seconds, for an MCP-admitting
    build or a prewarm). The HUD read runs on every turn's context build, so it must not
    queue behind another root's build: the peek is lock-free."""

    import threading

    from agent_runtime.chat_lane_tool_form import settled_surface_receipt

    _resident(registry, root="chat-root-1", signature="sig", receipt=_RECEIPT)
    building, release = threading.Event(), threading.Event()

    def _slow_factory():
        building.set()
        release.wait(10)
        return SimpleNamespace()

    builder = threading.Thread(
        target=lambda: registry.acquire(root_session_id="other-root", active_session_id="other-root",
                                        signature="s2", revision="r", factory=_slow_factory),
        daemon=True,
    )
    builder.start()
    try:
        assert building.wait(5)
        result: list = []
        reader = threading.Thread(
            target=lambda: result.append(settled_surface_receipt("chat-root-1", signature="sig")),
            daemon=True,
        )
        reader.start()
        reader.join(1.0)
        assert result == [_RECEIPT], "the HUD read waited on another root's actor build"
    finally:
        release.set()
        builder.join(5)
