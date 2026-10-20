"""``hermes namespace seed`` carries persona instances REBASED (row RT-NAMESPACE-SEED-HIRED-INSTANCES). Temp roots only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import namespace_seed as seeding
from agent_runtime.models import OfficeActor, OfficeItem, PersonaInstance
from agent_runtime.namespace_seed import instances as carry
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState
from hermes_cli import _namespace_bootstrap as ns

ACCT = "acct-0123456789abcdef"
HIRED = "personainst_neko_supervisor_agent_07c76f93"
CANONICAL = "personainst_neko_supervisor"
ORPHAN = "personainst_dev_agent_8b319ebf"  # placed in the office; the source holds no record
LEGACY = "personainst_operator_c2728fe710acb898"  # an alias-registry id


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


def _write(path: Path, body: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def _instance(base: Path, instance_id: str, **overrides) -> dict:
    record = PersonaInstance(
        id=instance_id, persona_id="neko_supervisor", role="neko_supervisor", display_name="Neko Mission Lead",
        profile_id="neko", runtime_root=str(base / "agent-runtime"), state=WorkerSessionState.RUNNING,
        mode="chat", realm_id="realm-1", workspace_id="ws_a", spawned_by="operator", model="claude-opus-5-5",
        provider="anthropic", api_mode="anthropic_messages", reasoning_effort="high", assigned_slots=["app"],
        primary_slot="app", session_id=f"persona_chat_{instance_id}_1", default_chat_session_id=f"persona_chat_{instance_id}_1",
        # a Windows path is case-insensitive: the source root spelled in another case and separator is still it
        chat_head_home=str(base / "profiles" / "base").upper().replace("\\", "/"),
        skill_manifest_hash="abc", active_run_id="run_1", current_assignment_id="asg_1", current_task_id="task_1",
        current_chat_goal="ship it", goal_id="goal_1", returned_to=CANONICAL, token_budget_used=4200,
    )
    return {**to_jsonable(record), "last_heartbeat_at": "2026-10-19T00:00:00.000000Z", **overrides}


def _actor(instance_id: str) -> dict:
    item = OfficeItem(item_id=instance_id, kind="agent", persona_id="neko_supervisor", display_name="x", folder="Agents")
    return to_jsonable(OfficeActor(actor_key=instance_id, workspace_id="ws_a", persona_id="neko_supervisor",
                                   persona_instance_id=instance_id, items=[item]))


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """A base root whose office places a hired instance, a canonical one and an orphan."""
    root = tmp_path / ".hermes"
    store = root / "agent-runtime"
    (root / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text("model: x\n", encoding="utf-8")
    _write(store / "persona_instances" / f"{HIRED}.json", _instance(root, HIRED))
    _write(store / "persona_instances" / f"{CANONICAL}.json", _instance(root, CANONICAL))
    _write(store / "persona_instances" / "personainst_broken.json", {})
    _write(store / "persona_instance_aliases.json", {LEGACY: CANONICAL})
    _write(store / "office" / "ws_a" / "office.json", {"workspace_id": "ws_a"})
    for placed in (HIRED, CANONICAL, ORPHAN):
        _write(store / "office" / "ws_a" / "actors" / f"{placed}.json", _actor(placed))
    return root


def _env(base: Path) -> dict[str, str]:
    return {"HERMES_DEPENDENCY_ROOT": str(base)}


def _seeded(base: Path) -> tuple[dict, ns.Layout]:
    env = _env(base)
    return seeding.seed(ACCT, "base", env, with_memories=True), ns.layout(ACCT, env)


def test_a_carried_record_is_rebased_cleared_and_keeps_its_definition(base: Path):
    """Red when a source-root path survives (case-blind match lost), a live binding travels, or a kept field drops."""
    _out, item = _seeded(base)
    row = json.loads((item.store_root / "persona_instances" / f"{HIRED}.json").read_text(encoding="utf-8"))
    assert row["runtime_root"] == str(item.store_root)
    assert row["chat_head_home"] == str(item.root / "PROFILES" / "BASE")  # the tail keeps its own spelling
    assert {name: row[name] for name in carry.CLEARED} == {
        **dict.fromkeys(set(carry.CLEARED) - {"state", "token_budget_used"}), "state": "idle", "token_budget_used": 0}
    kept = {"model": "claude-opus-5-5", "provider": "anthropic", "api_mode": "anthropic_messages",
            "reasoning_effort": "high", "realm_id": "realm-1", "workspace_id": "ws_a", "assigned_slots": ["app"],
            "primary_slot": "app", "display_name": "Neko Mission Lead", "persona_id": "neko_supervisor",
            "profile_id": "neko", "role": "neko_supervisor", "mode": "chat", "spawned_by": "operator"}
    assert {name: row[name] for name in kept} == kept
    assert str(base).casefold() not in json.dumps(row).casefold().replace("\\\\", "\\")


def test_placed_instances_resolve_in_the_seeded_namespace_and_orphans_do_not(base: Path, monkeypatch):
    """Red when the carried records (or the alias registry) are not written where the runtime's store reads them."""
    out, item = _seeded(base)
    assert out["instances"]["placements"] == {
        "resolved": [CANONICAL, HIRED], "orphaned": [{"id": ORPHAN, "reason": "placed but no source instance"}]}
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(item.store_root))
    monkeypatch.setenv("HERMES_HOME", str(item.head_home))
    from agent_runtime.office_store import OfficeStore
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_instance_identity import office_placement_evidence

    live, _archived = office_placement_evidence(OfficeStore())  # the placements the office projection reads
    assert live == {HIRED, CANONICAL, ORPHAN}
    store = PersonaInstanceStore()
    assert {row.id for row in store.list_all()} >= {HIRED, CANONICAL}
    assert store.get(HIRED).id == HIRED and store.get(CANONICAL).id == CANONICAL
    assert store.get(LEGACY).id == CANONICAL  # a legacy id resolves only through the carried alias registry
    with pytest.raises(FileNotFoundError):
        store.get(ORPHAN)


def test_a_value_still_naming_the_source_root_refuses_and_copies_nothing(base: Path):
    """Red when the leftover check is gone: a kept field mentioning the source root would ship unrebased."""
    path = base / "agent-runtime" / "persona_instances" / f"{HIRED}.json"
    _write(path, _instance(base, HIRED, display_name=f"works in {base}\\agent-runtime"))
    env = _env(base)
    for dry_run in (True, False):
        with pytest.raises(ns.NamespaceRefused) as caught:
            seeding.seed(ACCT, "base", env, dry_run=dry_run)
        assert caught.value.reason is ns.Reason.INSTANCE_NOT_REBASED
        assert not (base.parent / "hermes-namespaces" / ACCT).exists()


def test_the_dry_run_shows_the_carried_group_and_writes_nothing(base: Path):
    """Red when the plan stops listing a carried instance, its rebased fields, its cleared fields or a skip."""
    plan = seeding.seed(ACCT, "base", _env(base), dry_run=True)
    assert not (base.parent / "hermes-namespaces").exists()
    group = plan["instances"]
    item = ns.layout(ACCT, _env(base))
    rows = {row["id"]: row for row in group["carried"]}
    assert set(rows) == {CANONICAL, HIRED}
    assert rows[HIRED]["rebased"] == {"runtime_root": str(item.store_root),
                                      "chat_head_home": str(item.root / "PROFILES" / "BASE")}
    assert rows[HIRED]["cleared"] == list(carry.CLEARED)
    assert group["skipped"] == [{"path": "agent-runtime/persona_instances/personainst_broken.json",
                                 "reason": "not a persona-instance record"}]
    assert group["aliases"] == "agent-runtime/persona_instance_aliases.json"


def test_a_record_the_target_already_holds_stays_the_target_s(base: Path):
    """Red when the carry overwrites a target record (the plan must say the target wins, and the write must obey)."""
    item = ns.layout(ACCT, _env(base))
    held = item.store_root / "persona_instances" / f"{HIRED}.json"
    _write(held, {"mine": True})
    plan = carry.plan_instances(base, item)
    assert {"path": f"agent-runtime/persona_instances/{HIRED}.json", "reason": carry.TARGET_HOLDS} in plan.skipped
    assert HIRED in plan.resolved
    carry.write_instances(plan)
    assert json.loads(held.read_text(encoding="utf-8")) == {"mine": True}
