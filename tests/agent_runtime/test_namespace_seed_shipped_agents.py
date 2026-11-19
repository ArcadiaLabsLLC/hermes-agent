"""A new namespace made from another one gets no second copy of a shipped agent. Temp roots only.

Row ``RT-NAMESPACE-SEED-SKIPS-SHIPPED-AGENTS`` (design § 3, owner 2026-11-19). The source holds
Neko and Base as references (Neko's record carrying a stale definition and the owner's model), a
user's own agent, and a hired Neko seat placed in its office. ``seed --dry-run`` lists the shipped
agents as resolved from the build and copies none; the real seed writes the build's reference with
the source's settings, carries the user's agent as today, and the placed seat still resolves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import namespace_seed as seeding
from agent_runtime.bundled_agents import reference_record, shipped_agent
from agent_runtime.models import AgentPersona, OfficeActor, OfficeItem, PersonaInstance
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState
from hermes_cli import _namespace_bootstrap as ns

ACCT = "acct-0123456789abcdef"
NEKO = "neko_supervisor"
HIRED = "personainst_neko_supervisor_agent_07c76f93"
SHIPPED_PATHS = ["agent-runtime/agents/base.json", "agent-runtime/agents/neko_supervisor.json"]


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


def _write(path: Path, body: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / ".hermes"
    store = root / "agent-runtime"
    (root / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text("model: x\n", encoding="utf-8")
    neko = reference_record(shipped_agent(NEKO))
    stale = {**to_jsonable(neko), "display_name": "Neko (an older build)", "skills": ["old-skill"],
             "bundled_version": "0000000000000000", "model": "claude-opus-5-5", "provider": "anthropic"}
    _write(store / "agents" / f"{NEKO}.json", stale)
    _write(store / "agents" / "base.json", to_jsonable(reference_record(shipped_agent("base"))))
    _write(store / "agents" / "dev.json", to_jsonable(AgentPersona("dev", "Dev", "developer", "sol", "openai", None)))
    seat = PersonaInstance(id=HIRED, persona_id=NEKO, role=NEKO, display_name="Neko Mission Lead", profile_id="neko",
                           runtime_root=str(store), workspace_id="ws_a", mode="chat", state=WorkerSessionState.IDLE)
    _write(store / "persona_instances" / f"{HIRED}.json", to_jsonable(seat))
    _write(store / "office" / "ws_a" / "office.json", {"workspace_id": "ws_a"})
    item = OfficeItem(item_id=HIRED, kind="agent", persona_id=NEKO, display_name="x", folder="Agents")
    _write(store / "office" / "ws_a" / "actors" / f"{HIRED}.json", to_jsonable(OfficeActor(
        actor_key=HIRED, workspace_id="ws_a", persona_id=NEKO, persona_instance_id=HIRED, items=[item])))
    return root


def _env(base: Path) -> dict[str, str]:
    return {"HERMES_DEPENDENCY_ROOT": str(base)}


def test_the_dry_run_lists_shipped_agents_as_resolved_from_the_build(base: Path):
    plan = seeding.seed(ACCT, "base", _env(base), dry_run=True)

    assert [row["path"] for row in plan["shipped"]] == SHIPPED_PATHS
    assert {row["reason"] for row in plan["shipped"]} == {"resolved from the build"}
    assert plan["shipped"][1]["version"] == shipped_agent(NEKO).version
    # The records are planned one by one: only the user's own agent is copied.
    assert [rel for rel in plan["copied"] if rel.startswith("agent-runtime/agents")] == ["agent-runtime/agents/dev.json"]
    assert not ns.layout(ACCT, _env(base)).root.exists()


def test_the_seed_writes_the_build_s_reference_and_the_seat_still_resolves(base: Path, monkeypatch):
    env = _env(base)
    out = seeding.seed(ACCT, "base", env)
    item = ns.layout(ACCT, env)

    agents = item.store_root / "agents"
    assert (agents / "dev.json").read_bytes() == (base / "agent-runtime" / "agents" / "dev.json").read_bytes()
    written = json.loads((agents / f"{NEKO}.json").read_text(encoding="utf-8"))
    definition = shipped_agent(NEKO).definition
    assert written["origin"] == "eternia" and written["bundled_version"] == shipped_agent(NEKO).version
    assert written["display_name"] == definition["display_name"] and written["skills"] == definition["skills"]
    assert (written["model"], written["provider"]) == ("claude-opus-5-5", "anthropic")  # the source's settings
    manifest = json.loads((item.root / "namespace.json").read_text(encoding="utf-8"))
    assert manifest["shipped"] == ["base", NEKO] == [row["id"] for row in out["shipped"]]

    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(item.store_root))
    monkeypatch.setenv("HERMES_HOME", str(item.head_home))
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.store import AgentStore

    seat = PersonaInstanceStore().get(HIRED)
    agent = AgentStore().get(seat.persona_id)
    assert agent.origin == "eternia" and agent.display_name == "Neko Mission Lead"
