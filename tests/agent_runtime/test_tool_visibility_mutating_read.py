"""``resolve_tool_visibility`` reads the mutating set ONCE per resolve (runtime-queue, 2026-10-09).

``_mutating_tools()`` is uncached on purpose (its app-function half is the live Launcher
registration) and each call takes ``launcher_app_functions._state.lock`` and rebuilds a
frozenset; it used to be called once per callable and once per blocked tool.
"""

from __future__ import annotations

from agent_runtime import tool_visibility as tv
from agent_runtime.models import AgentPersona


def _persona() -> AgentPersona:
    return AgentPersona(id="dev", display_name="Launcher Dev", role="dev", model=None, provider=None,
                        api_mode="codex_responses", system_prompt_path="personas/dev/system.md")


def test_one_mutating_read_per_resolve_and_the_flags_still_follow_it(monkeypatch):
    tv._ensure_tool_registry_populated()
    first = tv.resolve_tool_visibility(_persona(), include_readiness=False)
    marked = first["final_model_tools"][0]
    assert first["final_tool_count"] > 1 and first["blocked_tools"], "the fixture must reach both loops"

    calls: list[int] = []

    def _counted() -> frozenset[str]:
        calls.append(1)
        return frozenset({marked})

    monkeypatch.setattr(tv, "_mutating_tools", _counted)
    resolved = tv.resolve_tool_visibility(_persona(), include_readiness=False)

    assert len(calls) == 1, f"{len(calls)} mutating reads for one resolve"
    # Positive control: the one read is the one every entry and the boundary consult.
    flags = {entry["name"]: entry["mutating"] for entry in resolved["callable_tools"]}
    assert flags[marked] is True and sum(flags.values()) == 1
    assert resolved["mutation_boundary"]["mutating_tools"] == [marked]
