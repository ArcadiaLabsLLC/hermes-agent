"""``runtime.operator.conversation.skills`` reaches a worker CHILD (RT-SERVE-SKILLS-OPERATOR-CHILD-ADDRESS).

The Launcher's worker snapshots all come from ``runtime.operator.conversation.subagents.*``, so the
``child_ref`` that lane mints must resolve on the operator skills verb too: ``list`` / ``detail`` /
``history`` read the child's own cwd, tools and session; ``operation: lend`` writes its lend and steers
it. Real dispatcher, stores and native child registry; the skill reader and the steer are fakes that
record what they were asked; the ``skill_lends`` record is the real one.
"""
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import serve_rpc, skill_lends
from agent_runtime.persona_chat_durability import default_persona_session_db
from tools.delegate_tool_child_run import _register_child
from tools.delegate_tool_registry import _unregister_subagent
from tests.agent_runtime.test_operator_session_inspection import target, inspect
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent  # noqa: F401 (fixtures)
from tests.agent_runtime.test_instance_conversation_owner import chat_head  # noqa: F401 (autouse fixture)


class Child:
    def __init__(self, key, cwd):
        self._subagent_id, self._delegate_depth, self.model = key, 1, "m"
        self.session_id, self.cwd, self.valid_tool_names = f"{key}-session", cwd, {"skill_view"}


@pytest.fixture
def world(placed_agent, tmp_path, monkeypatch):
    from agent import runtime_cwd
    from agent_runtime import skill_inspection
    from agent_runtime.chat_verbs import queue_skill
    from tools import delegate_tool_registry

    seen = SimpleNamespace(cwd=[], steers=[], rejected={})
    monkeypatch.setattr(runtime_cwd, "set_session_cwd", lambda cwd: seen.cwd.append(cwd) or "token")
    monkeypatch.setattr(runtime_cwd, "reset_session_cwd", lambda token: None)
    reader = SimpleNamespace(catalog=lambda can_load: [{"id": "git", "can_load": can_load}],
                             detail=lambda skill_id, can_load: {"id": skill_id, "can_load": can_load})
    monkeypatch.setattr(skill_inspection, "skill_inspection_reader", lambda: reader)
    monkeypatch.setattr(queue_skill, "_rejected_skills",
                        lambda skills: {s: seen.rejected[s] for s in skills if s in seen.rejected})
    monkeypatch.setattr(delegate_tool_registry, "steer_subagent",
                        lambda subagent_id, text, authorize_record=None: seen.steers.append((subagent_id, text)) or True)
    params = target(placed_agent["persona_instance_id"])
    child = Child("worker-1", str(tmp_path / "child-cwd"))
    with closing(default_persona_session_db()) as db:
        child._session_db = db
        child.logs_dir = Path(db.db_path).parent / "sessions"
        _register_child(child, SimpleNamespace(session_id=params["session_id"]), "work", owner_session_id=None,
                        owner_transport=None, owner_session_record=None)
        try:
            listed = inspect("subagents.list", params)
            assert "result" in listed, listed
            roster = listed["result"]
            ref = roster["children"][0]["child_ref"]
            yield SimpleNamespace(params=params, ref=ref, child=child, seen=seen)
        finally:
            _unregister_subagent("worker-1", agent=child)


def _skills(world, operation, **extra):
    return inspect("skills", {**world.params, "operation": operation, **extra})


def test_a_child_ref_reads_the_childs_catalog_not_the_parents(world):
    listed = _skills(world, "list", child_ref=world.ref)
    assert "result" in listed, listed
    assert listed["result"]["skills"] == [{"id": "git", "can_load": True}]
    assert listed["result"]["lent"] == [] and listed["result"]["child_ref"] == world.ref
    assert world.seen.cwd == [world.child.cwd], "the child's own working directory"
    detail = _skills(world, "detail", child_ref=world.ref, skill_id="git")["result"]
    assert detail["skill"] == {"id": "git", "can_load": True}
    history = _skills(world, "history", child_ref=world.ref)["result"]
    assert history["loaded"] == [] and history["historyComplete"] is False


def test_a_stale_or_foreign_child_ref_is_the_subagent_refusal(world):
    stale = _skills(world, "list", child_ref="not-a-ref")
    assert stale["error"]["data"]["reason"] == "subagent_reference_stale"
    _unregister_subagent("worker-1", agent=world.child)
    gone = _skills(world, "list", child_ref=world.ref)
    assert gone["error"]["data"]["reason"] == "subagent_reference_stale"
    assert world.seen.cwd == [], "a refused child read reads nothing"


def test_lend_writes_the_childs_lend_and_steers_it(world):
    reply = _skills(world, "lend", child_ref=world.ref, skills=["git"], request_id="l1")
    assert "result" in reply, reply
    data = reply["result"]
    assert (data["target"], data["skills_lent"], data["effective"], data["steered"]) == \
        ("child:worker-1", ["git"], "next_turn", True)
    assert skill_lends.lent_to("child:worker-1") == ("git",)
    assert world.seen.steers == [("worker-1", "Skills lent: git. Load one with skill_view(<id>) when it applies.")]
    roster = inspect("subagents.list", world.params)["result"]
    assert roster["children"][0]["skills_lent"] == ["git"]
    revoked = _skills(world, "lend", child_ref=world.ref, skills=["git"], mode="revoke", request_id="l2")["result"]
    assert revoked["skills_lent"] == [] and skill_lends.lent_to("child:worker-1") == ()


def test_a_lend_is_refused_typed(world):
    world.seen.rejected = {"ghost": "not_found"}
    refused = _skills(world, "lend", child_ref=world.ref, skills=["git", "ghost"], request_id="l1")["error"]["data"]
    assert refused == {"reason": "skills_not_loadable", "rejected_skills": {"ghost": "not_found"}}
    assert skill_lends.lent_to("child:worker-1") == () and world.seen.steers == []
    bad_mode = _skills(world, "lend", child_ref=world.ref, skills=["git"], mode="borrow", request_id="l1")
    assert bad_mode["error"]["data"]["reason"] == "invalid_lend_request"
    no_child = _skills(world, "lend", skills=["git"], request_id="l1")
    assert no_child["error"]["data"]["reason"] == "subagent_request_invalid"


def test_without_a_child_ref_the_verb_still_reads_the_conversation(world):
    own = _skills(world, "list")
    assert "result" in own, own
    assert "lent" not in own["result"] and "child_ref" not in own["result"]


def test_the_manifest_publishes_the_operator_child_address_and_lend():
    params = serve_rpc.manifest()["params"]["runtime.operator.conversation.skills"]
    assert {"operation", "child_ref", "skill_id", "skills", "mode", "request_id"} <= set(params)
