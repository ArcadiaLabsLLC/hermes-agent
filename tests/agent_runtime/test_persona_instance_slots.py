"""A persona instance's repo-slot assignment (plan ``build-running-work-2026-10-04.md`` §3.3, row H5b).

The instance record is the AUTHORITY (owner correction 2026-10-04): a subset of the
workspace's declared slots, never "all", shared freely across instances (owner example), with
ONE primary that defaults to the first assigned and says so (owner full-stack).
"""

from __future__ import annotations

from hermes_time import now

from agent_runtime import paths, serve_rpc
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import declare

T0 = "2026-10-04T12:00:00+00:00"
T1 = "2026-10-04T13:00:00+00:00"
T2 = "2026-10-04T14:00:00+00:00"


def _slot(name: str) -> dict:
    return {"name": name, "repo": {"clone_url": f"https://github.com/ArcadiaLabsLLC/{name}.git"}}


def _instance(instance_id: str, workspace_id: str | None) -> str:
    store = PersonaInstanceStore()
    store._write(PersonaInstance(
        id=instance_id, persona_id="dev", role="dev", display_name=instance_id, profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace_id, updated_at=now(),
    ))
    return instance_id


def call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _setup(*slots: str) -> str:
    workspace = WorkspaceStore().create(name="Team").id
    declare(workspace, [_slot(name) for name in slots], issued_at=T0, machine="mach_test")
    return workspace


def _set(instance_id, slots, primary=None, issued_at=T1):
    return call("runtime.persona.instance.slots.set",
                {"persona_instance_id": instance_id, "slots": slots, "primary": primary, "issued_at": issued_at})


def test_a_slot_outside_the_workspace_and_a_primary_outside_the_set_are_refused():
    workspace = _setup("launcher", "backend")
    agent = _instance("personainst_frontend", workspace)
    assert _set(agent, ["launcher", "hermes"])["error"]["data"]["reason"] == "slot_not_in_workspace"
    assert _set(agent, ["launcher"], primary="backend")["error"]["data"]["reason"] == "primary_not_assigned"
    assert PersonaInstanceStore().get(agent).assigned_slots == []
    # Positive control: the same instance, a valid subset.
    assert _set(agent, ["launcher"])["result"]["slots"][0]["name"] == "launcher"


def test_the_canonical_channel_has_no_assignment():
    _setup("launcher")
    lone = _instance("personainst_lone", None)
    assert _set(lone, ["launcher"])["error"]["data"]["reason"] == "instance_has_no_workspace"


def test_two_instances_share_a_slot_and_setting_one_never_moves_the_other():
    workspace = _setup("launcher", "backend", "contracts")
    frontend, backend = _instance("personainst_fe", workspace), _instance("personainst_be", workspace)
    _set(frontend, ["launcher", "contracts"])
    _set(backend, ["backend", "contracts"])
    _set(frontend, ["launcher"], issued_at=T2)
    store = PersonaInstanceStore()
    assert store.get(frontend).assigned_slots == ["launcher"]
    assert store.get(backend).assigned_slots == ["backend", "contracts"]


def test_the_primary_is_explicit_first_assigned_or_none_and_says_which():
    workspace = _setup("launcher", "backend")
    agent = _instance("personainst_full", workspace)
    shown = _set(agent, ["backend", "launcher"], primary="launcher")["result"]
    assert (shown["primary_slot"], shown["primary_source"]) == ("launcher", "explicit")
    shown = _set(agent, ["backend", "launcher"], issued_at=T2)["result"]
    assert (shown["primary_slot"], shown["primary_source"]) == ("backend", "first_assigned")
    shown = _set(agent, [], issued_at="2026-10-04T15:00:00+00:00")["result"]
    assert (shown["slots"], shown["primary_slot"], shown["primary_source"]) == ([], None, "none")


def test_a_removed_slot_leaves_every_assignment_and_clears_a_primary_that_left():
    workspace = _setup("launcher", "backend")
    agent = _instance("personainst_rm", workspace)
    _set(agent, ["launcher", "backend"], primary="backend")
    result = declare(workspace, [_slot("launcher")], issued_at=T2, machine="mach_test")
    assert result["assignments_dropped"] == [agent]
    row = PersonaInstanceStore().get(agent)
    assert (row.assigned_slots, row.primary_slot) == (["launcher"], None)


def test_a_stale_whole_row_write_cannot_revert_a_newer_assignment():
    workspace = _setup("launcher")
    agent = _instance("personainst_turn", workspace)
    store = PersonaInstanceStore()
    held = store.get(agent)  # a chat turn loads the row at admission …
    _set(agent, ["launcher"])  # … the console assigns a slot mid-turn …
    held.display_name = "settled"
    store.update(held)  # … and the turn's settle writes its old copy back.
    row = store.get(agent)
    assert row.assigned_slots == ["launcher"] and row.display_name == "settled"


def test_an_older_assignment_is_refused_and_there_is_no_count_limit():
    names = [f"s{i}" for i in range(100)]
    workspace = _setup(*names)
    agent = _instance("personainst_many", workspace)
    assert len(_set(agent, names, issued_at=T2)["result"]["slots"]) == 100
    assert _set(agent, ["s1"], issued_at=T1)["error"]["data"]["reason"] == "stale_revision"


def test_the_assignment_travels_with_the_persona_instance_family():
    from agent_runtime.persona_instance_sync.contract import PERSONA_INSTANCE_ALLOWED_KEYS

    assert {"assigned_slots", "primary_slot", "slots_issued_at"} <= PERSONA_INSTANCE_ALLOWED_KEYS
