"""Readiness on demand: a build readies Home's agent and the agents someone asked for.

Owner ruling 2026-11-22: "Agent readiness it should only ready the first one in
the drop down and then the rest on first message". Rows
RT-FU-THE-FIRST-AGENT-LIST-AFTER-AN-UPDATE-WAITS-SEVEN-SECONDS-ON-AGENT-READINESS,
RT-FU-THE-SNAPSHOT-WORKER-LOADS-EVERY-PLUGIN-TWICE-IN-ITS-FIRST-BUILD and
RT-FU-PERSONA-PREWARM-PAYS-SECONDS-FOR-EVERY-AGENT-TYPE (lane w1122g-readiness).

Named mutations, red recorded 2026-11-22, each alone, restored:
* ``sections.agents_readiness`` walking every agent (``in wanted`` -> ``True``)
  -> "a build walks only Home's agent and the readied ones" red;
* ``summaries._agent_summary`` resolving visibility for a not-checked row
  (``checked = True``) -> "a not-checked agent resolves no tools" red;
* ``persona_prewarm.request_persona_prewarm`` without ``mark_readied`` -> "a
  prewarm readies the agent for every later build" red;
* ``serve_rpc.chat._runtime_chat_message`` without ``_ready_on_first_message``
  -> "an agent's first message readies it" red;
* ``skills_resolver._walk_skill_catalog`` without its process-home binding ->
  "a cold build loads the plugins once" red;
* ``readiness_demand.home_agent_candidates`` with Base before Neko -> "Home's
  agent is Neko, else Base, else the only agent" red;
* ``snapshot_worker.child.handle_build`` without ``recorded_readied`` -> "the
  worker builds with the serve's readied set" red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import readiness_demand
from agent_runtime.readiness_demand import (
    READINESS_NOT_CHECKED,
    home_agent_persona_id,
    mark_readied,
    readied_persona_ids,
    recorded_readied,
)


def _persona(persona_id: str, profile: str | None = None):
    from agent_runtime.models import AgentPersona

    return AgentPersona(
        id=persona_id,
        display_name=persona_id.replace("_", " ").title(),
        role="qa",
        model=None,
        provider=None,
        api_mode=None,
        system_prompt_path="",
        hermes_profile=profile,
    )


@pytest.fixture
def three_agents(isolate_agent_runtime_root):
    from agent_runtime.store import AgentStore

    store = AgentStore()
    personas = [_persona("neko_supervisor"), _persona("base"), _persona("qa_helper")]
    for persona in personas:
        store.save(persona)
    return personas


@pytest.fixture
def walked(monkeypatch):
    """The persona ids the readiness walk ran for."""

    from agent_runtime import profile_readiness

    seen: list[str] = []
    real = profile_readiness.profile_readiness_for_persona

    def counting(persona, **kwargs):
        seen.append(persona.id)
        return real(persona, **kwargs)

    monkeypatch.setattr(profile_readiness, "profile_readiness_for_persona", counting)
    return seen


def _rows(snapshot) -> dict[str, dict]:
    return {
        row["persona_id"]: row
        for row in snapshot["agents"]
        if row.get("runtime_agent_kind") != "persona_instance"
    }


def test_homes_agent_is_neko_else_base_else_the_only_agent():
    neko, base, other = _persona("neko_supervisor"), _persona("base"), _persona("qa_helper")
    assert home_agent_persona_id([base, other, neko]) == "neko_supervisor"
    assert home_agent_persona_id([other, base]) == "base"
    assert home_agent_persona_id([other, _persona("dev", profile="base")]) == "dev", "a Base by its profile"
    assert home_agent_persona_id([other]) == "qa_helper"
    assert home_agent_persona_id([other, _persona("dev")]) is None, "no Neko, no Base, two agents: no guess"


def test_a_build_walks_only_homes_agent_and_the_readied_ones(three_agents, walked):
    from agent_runtime.snapshot import build_snapshot

    rows = _rows(build_snapshot())
    assert walked == ["neko_supervisor"]
    assert rows["neko_supervisor"]["home_agent"] is True
    assert rows["neko_supervisor"]["profile_readiness"] != READINESS_NOT_CHECKED
    for other in ("base", "qa_helper"):
        assert rows[other]["profile_readiness"] == READINESS_NOT_CHECKED
        assert rows[other]["readiness_summary"] == "Not checked yet"
        assert rows[other]["home_agent"] is False

    walked.clear()
    mark_readied("qa_helper")
    rows = _rows(build_snapshot())
    assert sorted(walked) == ["neko_supervisor", "qa_helper"]
    assert rows["qa_helper"]["profile_readiness"] != READINESS_NOT_CHECKED
    assert rows["base"]["profile_readiness"] == READINESS_NOT_CHECKED


def test_a_not_checked_agent_resolves_no_tools(three_agents, monkeypatch):
    from agent_runtime.snapshot import build_snapshot
    from agent_runtime.snapshot import summaries

    resolved: list[str] = []
    real = summaries.resolve_tool_visibility

    def counting(agent, *args, **kwargs):
        resolved.append(agent.id)
        return real(agent, *args, **kwargs)

    monkeypatch.setattr(summaries, "resolve_tool_visibility", counting)
    rows = _rows(build_snapshot())
    assert resolved == ["neko_supervisor"]
    assert rows["base"]["tool_count"] is None
    assert rows["base"]["permission_mode"] is None
    assert rows["neko_supervisor"]["tool_count"] is not None, "positive control: the walked row has its tools"


def test_a_prewarm_readies_the_agent_for_every_later_build(three_agents, monkeypatch):
    from agent_runtime import persona_prewarm

    monkeypatch.setattr(persona_prewarm, "_ensure_worker", lambda: None)
    outcome = persona_prewarm.request_persona_prewarm({"persona_id": "qa_helper"})
    assert outcome.refusal is None
    assert "qa_helper" in readied_persona_ids()
    assert "qa_helper" in persona_prewarm._publish, "the first ask publishes the readied row"
    with persona_prewarm._lock:
        persona_prewarm._pending.clear()
        persona_prewarm._publish.clear()
    while not persona_prewarm._queue.empty():
        persona_prewarm._queue.get_nowait()
        persona_prewarm._queue.task_done()


def test_an_agents_first_message_readies_it(three_agents, monkeypatch):
    from agent_runtime import chat_turn
    from agent_runtime import persona_prewarm
    from agent_runtime.serve_rpc import chat

    monkeypatch.setattr(persona_prewarm, "_ensure_worker", lambda: None)
    monkeypatch.setattr(
        chat_turn, "perform_chat_turn",
        lambda params, **_: SimpleNamespace(refusal=None, result={"accepted": True}),
    )
    reply = chat._runtime_chat_message("r1", {"persona_id": "base", "message": "hi", "turn_request_id": "t"})
    assert "error" not in reply
    assert "base" in readied_persona_ids()
    with persona_prewarm._lock:
        persona_prewarm._pending.clear()
        persona_prewarm._publish.clear()
    while not persona_prewarm._queue.empty():
        persona_prewarm._queue.get_nowait()
        persona_prewarm._queue.task_done()


def test_the_readied_row_is_a_merge_carrying_the_walked_readiness(three_agents):
    from agent_runtime.events import EventLog
    from agent_runtime.state_patches.persona import emit_persona_readied

    log = EventLog()
    assert emit_persona_readied(log, three_agents[1]) is True
    patch = [event for event in log.tail(20) if event.type == "state.patched"][-1].payload
    assert patch["entity"] == "persona" and patch["id"] == "base"
    assert patch["op"] == "upsert" and not patch.get("created"), "a merge onto the held row"
    assert patch["changed"]["profile_readiness"] != READINESS_NOT_CHECKED
    assert patch["changed"]["home_agent"] is False


def test_the_worker_builds_with_the_serves_readied_set(isolate_agent_runtime_root, monkeypatch):
    from agent_runtime.snapshot_worker import child

    seen: list[frozenset[str]] = []
    monkeypatch.setattr(
        "agent_runtime.snapshot.build._build_snapshot_uncoalesced",
        lambda: seen.append(readied_persona_ids()) or {},
    )
    child.handle_build({"readied": ["qa_helper"]})
    assert seen == [frozenset({"qa_helper"})]
    with recorded_readied(None):
        assert readied_persona_ids() == frozenset(), "outside a worker build: this process's own set"


def test_a_cold_build_loads_the_plugins_once(tmp_path, monkeypatch):
    """The catalog walk runs under the process home whichever persona's home is bound."""

    from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override

    from agent_runtime.prompt_observability import skills_resolver

    process_home = tmp_path / "process-home"
    persona_home = tmp_path / "process-home" / "profiles" / "neko"
    persona_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(process_home))
    homes: list[str] = []
    token = set_hermes_home_override(persona_home)
    try:
        skills_resolver._walk_skill_catalog(lambda: homes.append(str(get_hermes_home())) or [])
        assert str(get_hermes_home()) == str(persona_home), "the persona binding is put back"
    finally:
        reset_hermes_home_override(token)
    assert homes == [str(process_home)]


@pytest.fixture(autouse=True)
def _fresh_demand():
    readiness_demand._reset()
    yield
    readiness_demand._reset()
