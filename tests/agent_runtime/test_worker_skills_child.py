"""``eternia.skills.*`` with the child address, and ``eternia.skills.lend`` (p10-work S2, RT-ETERNIA-SKILLS-LENDS-SKILLS).

Plan ``docs/agent-runtime-harness/archive/p10-work-2026-10-19.md`` §4.4. A fake owner session (the
``tests/tui_gateway/test_subagent_snapshot.py`` runtime) holds a child registered through upstream's own
``_register_child``; the request runs under that session's bound transport, as a gateway dispatch does.
The skill reader, the state db, the compact-category walk and the steer are fakes that record what they
were asked; the ``skill_lends`` record is the real one on this test's isolated store.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import skill_lends
from agent_runtime.chat_lane_skill_index import COMPACT_ATTR
from agent_runtime.conversations import worker_skills
from agent_runtime.subagents import native
from agent_runtime.subagents.references import references
from tests.tui_gateway.test_subagent_snapshot import runtime  # the fixture

ADDRESS = {"owner_scope": "owned-route", "worker_generation": "worker-1"}


class Child:
    def __init__(self, key, cwd):
        self._subagent_id, self._delegate_depth, self.model = key, 1, "m"
        self.session_id, self.cwd, self.valid_tool_names = f"{key}-session", cwd, {"skill_view", "terminal"}


@pytest.fixture
def world(runtime, monkeypatch, tmp_path):
    from tools.delegate_tool_child_run import _register_child
    from tui_gateway import server
    from tui_gateway.transport import _current_transport, bind_transport

    _server, owner, transport, _call = runtime
    child = Child("child-1", str(tmp_path / "child-cwd"))
    _register_child(child, None, "review", owner_session_id="ui-owner", owner_transport=transport,
                    owner_session_record=owner)
    seen = SimpleNamespace(cwd=[], keys=[], steers=[], rejected={}, compact={"git": frozenset({"b", "c"})})
    snapshot = {"info": {"cwd": str(tmp_path / "parent-cwd"), "tools": {}}, "session_key": "parent-session"}
    monkeypatch.setattr(server, "handle_request", lambda request: {"result": snapshot})

    from agent import runtime_cwd
    import hermes_state_registry
    from agent_runtime import skill_activity, skill_inspection
    from agent_runtime import chat_lane_skill_index
    from agent_runtime.chat_verbs import queue_skill

    monkeypatch.setattr(runtime_cwd, "set_session_cwd", lambda cwd: seen.cwd.append(cwd) or "token")
    monkeypatch.setattr(runtime_cwd, "reset_session_cwd", lambda token: None)
    db = SimpleNamespace(get_messages_as_conversation=lambda key, include_ancestors: seen.keys.append(key) or [key])
    monkeypatch.setattr(hermes_state_registry, "acquire", lambda path: db)
    monkeypatch.setattr(hermes_state_registry, "release_or_close", lambda handle: None)
    monkeypatch.setattr(skill_activity, "skill_load_history", lambda messages: list(messages))
    reader = SimpleNamespace(catalog=lambda can_load: [{"id": "git", "can_load": can_load}],
                             detail=lambda skill_id, can_load: {"id": skill_id, "can_load": can_load})
    monkeypatch.setattr(skill_inspection, "skill_inspection_reader", lambda: reader)
    monkeypatch.setattr(queue_skill, "_rejected_skills", lambda skills: {s: seen.rejected[s] for s in skills
                                                                          if s in seen.rejected})
    monkeypatch.setattr(chat_lane_skill_index, "compact_skill_categories",
                        lambda keep, roots=None: frozenset.intersection(*(seen.compact[s] for s in keep)))
    monkeypatch.setattr(native, "steer_child",
                        lambda params, text, request_id: seen.steers.append((text, request_id)) or "queued")
    token = bind_transport(transport)
    try:
        owner_tuple = native._native_owner({"session_id": "ui-owner", **ADDRESS})[0]
        record = next(r for r in native.registry_snapshot() if r.get("agent") is child)
        ref = references.child(owner_tuple, record)
        yield SimpleNamespace(child=child, owner=owner, ref=ref, seen=seen)
    finally:
        _current_transport.reset(token)


def _params(world, **extra):
    return {"session_id": "ui-owner", **ADDRESS, "child_ref": world.ref, **extra}


def _read(operation, params):
    return worker_skills._read_method(operation)("r", params)


def test_list_detail_history_with_a_child_ref_read_the_childs_session_and_cwd(world):
    listed = _read("list", _params(world))["result"]["data"]
    assert listed == {"skills": [{"id": "git", "can_load": True}], "lent": []}
    assert world.seen.cwd == [world.child.cwd]
    assert _read("detail", _params(world, skill_id="git"))["result"]["data"]["skill"]["can_load"] is True
    history = _read("history", _params(world))["result"]["data"]
    assert world.seen.keys == ["child-1-session"] and history["loaded"] == ["child-1-session"]
    # Without the address the same methods read the session itself.
    own = _read("history", {"session_id": "ui-owner"})["result"]["data"]
    assert world.seen.keys[-1] == "parent-session" and own["loaded"] == ["parent-session"]
    assert _read("list", {"session_id": "ui-owner"})["result"]["data"] == {"skills": [{"id": "git", "can_load": False}]}


def test_a_stale_generation_is_refused_typed_not_served(world):
    from tools.delegate_tool_registry import _unregister_subagent

    stale = _read("history", _params(world, worker_generation="worker-0"))
    assert stale["error"]["code"] == 4602 and stale["error"]["data"]["reason"] == "subagent_reference_stale"
    _unregister_subagent("child-1", agent=world.child)
    gone = _read("list", _params(world))
    assert gone["error"]["data"]["reason"] == "subagent_reference_stale"
    assert world.seen.keys == [] and world.seen.cwd == [], "a refused child read reads nothing"


def test_mixed_child_params_are_invalid(world):
    partial = _read("list", {"session_id": "ui-owner", "owner_scope": "owned-route", "child_ref": world.ref})
    assert partial["error"]["code"] == 4090 and partial["error"]["data"]["reason"] == "invalid_request"
    task = worker_skills.lend_method("r", {"session_id": "ui-owner", "skills": ["git"], "request_id": "q"})
    assert task["error"]["data"]["reason"] == "invalid_request" and "runtime.work.lend_skills" in task["error"]["data"]["detail"]


def test_lend_writes_the_record_sets_the_childs_compact_categories_and_steers(world):
    world.owner["agent"] = SimpleNamespace(**{COMPACT_ATTR: frozenset({"a", "b", "c"})})
    reply = worker_skills.lend_method("r", _params(world, skills=["git"], mode="lend", request_id="l1"))["result"]["data"]
    assert reply == {"target": "child:child-1", "skills_lent": ["git"], "effective": "next_turn", "steered": True}
    assert skill_lends.lent_to("child:child-1") == ("git",)
    assert getattr(world.child, COMPACT_ATTR) == frozenset({"b", "c"}), "the parent's compact set less the lent category"
    assert world.seen.steers == [("Skills lent: git. Load one with skill_view(<id>) when it applies.", "lend:l1")]
    assert _read("list", _params(world))["result"]["data"]["lent"] == ["git"]


def test_revoke_removes_the_record_and_recomputes(world):
    world.owner["agent"] = SimpleNamespace(**{COMPACT_ATTR: frozenset({"a", "b", "c"})})
    worker_skills.lend_method("r", _params(world, skills=["git"], request_id="l1"))
    reply = worker_skills.lend_method("r", _params(world, skills=["git"], mode="revoke", request_id="l2"))
    assert reply["result"]["data"]["skills_lent"] == [] and skill_lends.lent_to("child:child-1") == ()
    assert getattr(world.child, COMPACT_ATTR) == frozenset(), "nothing lent: back to the built, unscoped child"
    assert world.seen.steers[-1][0].startswith("Skills no longer lent: git.")


def test_an_unloadable_skill_refuses_the_whole_lend(world):
    world.seen.rejected = {"ghost": "not_found"}
    reply = worker_skills.lend_method("r", _params(world, skills=["git", "ghost"], request_id="l1"))
    assert reply["error"]["code"] == 4090
    assert reply["error"]["data"] == {"reason": "skills_not_loadable", "rejected_skills": {"ghost": "not_found"}}
    assert skill_lends.lent_to("child:child-1") == () and world.seen.steers == []
    assert not hasattr(world.child, COMPACT_ATTR)


def test_the_roster_row_carries_skills_lent(world):
    skill_lends.lend("child:child-1", ["git"], owner_session="ui-owner", by="test")
    owner_tuple = native._native_owner({"session_id": "ui-owner", **ADDRESS})[0]
    exact = native._native_owner({"session_id": "ui-owner", **ADDRESS})[3]
    rows = native._child_roster(owner=owner_tuple, records=native.registry_snapshot(), exact=exact,
                                controllable=exact)["children"]
    assert [row["skills_lent"] for row in rows] == [["git"]]
