"""Real room policy, routing receipts and journals; only provider workers are doubled."""
from contextlib import closing

import pytest

from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.service import ConversationService
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.discussions.service import DiscussionService
from tests.agent_runtime.conversation_support import WorkerFactory
from tests.agent_runtime.test_discussion_runtime import wait_until

pytestmark = pytest.mark.timeout(90)


@pytest.fixture
def groups(tmp_path):
    for name in ("runtime", "home", "a", "b", "work"):
        (tmp_path / name).mkdir()
    factory = WorkerFactory()
    conversations = ConversationService(tmp_path / "runtime", "install", profile_home=lambda p: tmp_path / p,
                                      worker_factory=factory)
    context = NativeContext(tmp_path / "runtime", tmp_path / "home", "install")
    service = DiscussionService(context, active_poll_interval=.02, conversations=lambda: conversations)
    service.start()
    yield service, conversations, factory, tmp_path
    service.close()
    conversations.close()


def create(groups, key="group", profiles=("a", "b")):
    service, _, _, root = groups
    scope = execute(service, "capabilities", {"client_scope": "account"}, actor_id="operator")["group_scope"]
    run = execute(service, "run.start_group", {"client_scope": "account", "idempotency_key": key,
        "workspace_id": scope,
        "spec": {"name": "Amelia, Builder", "cwd": str(root / "work"), "participants": [
            {"install_id": "install", "profile": p, "home": str(root / p), "name": p} for p in profiles]}},
        actor_id="operator")["run"]
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "open")
    return run


def act(service, run, op, key, **fields):
    return execute(service, "run." + op, {"client_scope": "account", "workspace_id": run["workspace_id"],
        "run_id": run["run_id"], "idempotency_key": key,
        "expect_revision": service.runs.get(run["run_id"])["revision"], **fields}, actor_id="operator")


def sends(factory):
    return [(w, p) for w in factory.workers for method, p in w.calls if method == "prompt.submit"]


def complete(factory, text="Idea", status="complete"):
    for worker in factory.workers:
        for sid, execution in list(worker.executions.items()):
            if execution["status"] == "running":
                worker.event(sid, "message.complete", text=text, status=status)


def idle(service, run, count):
    view = service.view(run["workspace_id"], run["run_id"])
    events = view["log"]["events"]
    return view if sum(e["kind"] == "room.activity" for e in events) >= count else None


def test_open_is_idle_without_office_or_agent_creation_and_has_private_scope(groups):
    service, conversations, factory, root = groups
    first = create(groups)
    second = create(groups, "another")
    assert create(groups)["run_id"] == first["run_id"]
    assert first["run_id"] != second["run_id"]
    assert not factory.workers
    assert service.view(first["workspace_id"], first["run_id"])["log"]["events"] == []
    with closing(service.runs.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM mc_discussion_instance_claims").fetchone()[0] == 0
    members = service.runs.members(first["run_id"])
    assert all(m["instance_id"] is None and m["persona_id"] is None for m in members)
    direct = conversations.open(ConversationScope("operator", "account", "a"), key="direct",
                                cwd=str(root / "work"), expected_home=str(root / "a"))
    assert direct["session_id"] not in {m["session_id"] for m in members}
    for actor, client in (("other", "account"), ("operator", "other")):
        with pytest.raises(DiscussionError, match="conversation owner changed"):
            execute(service, "run.get", {"client_scope": client, "workspace_id": first["workspace_id"],
                "run_id": first["run_id"]}, actor_id=actor)
    with pytest.raises(DiscussionError, match="conversation owner changed"):
        execute(service, "run.start_group", {"client_scope": "account", "workspace_id": "ws",
            "idempotency_key": "wrong-scope", "spec": {k: first["initial"]["group"][k]
                for k in ("name", "participants", "cwd")}}, actor_id="operator")


def test_compare_then_discuss_and_exact_reply_keep_one_group(groups):
    service, _, factory, _ = groups
    run = create(groups)
    act(service, run, "send", "compare", message="Find an idea", response={"mode": "compare", "members": []})
    wait_until(lambda: len(sends(factory)) == 2)
    assert all("independent answer" in p["text"] for _, p in sends(factory))
    act(service, run, "send", "compare", message="Find an idea", response={"mode": "compare", "members": []})
    assert len(sends(factory)) == 2
    complete(factory, "A distinctive idea")
    wait_until(lambda: idle(service, run, 1))
    act(service, run, "send", "discuss", message="Develop the best idea")
    wait_until(lambda: len(sends(factory)) == 3)
    continued = next(p["text"] for _, p in sends(factory) if "Develop the best idea" in p["text"])
    assert "A distinctive idea" in continued
    complete(factory)
    wait_until(lambda: len(sends(factory)) == 4)
    complete(factory)
    view = wait_until(lambda: idle(service, run, 2))
    target = view["members"][1]
    act(service, run, "send", "target", message="Explain", response={"mode": "reply", "members": [target["member_id"]]})
    wait_until(lambda: len(sends(factory)) == 5)
    complete(factory)
    view = wait_until(lambda: idle(service, run, 3))
    assert len([e for e in view["log"]["events"] if e["kind"] == "message.user"]) == 3
    assert len(sends(factory)) == 5


def test_missing_profile_does_not_block_opening_or_other_replies(groups):
    service, _, factory, _ = groups
    run = create(groups, profiles=("a", "missing"))
    act(service, run, "send", "compare", message="Hi", response={"mode": "compare", "members": []})
    wait_until(lambda: len(sends(factory)) == 1)
    complete(factory)
    view = wait_until(lambda: idle(service, run, 1))
    assert len([e for e in view["log"]["events"] if e["kind"] == "message.member"]) == 1
    assert any(t["status"] == "failed" for t in view["tasks"])


def test_native_question_ack_and_confirmed_stop_share_exact_execution(groups):
    service, _, factory, _ = groups
    run = create(groups)
    target = service.runs.members(run["run_id"])[0]["member_id"]
    act(service, run, "send", "ask", message="Do this", response={"mode": "reply", "members": [target]})
    wait_until(lambda: len(sends(factory)) == 1)
    worker, sent = sends(factory)[0]
    worker.question(sent["session_id"], "srq-permission", command="read file", choices=["once", "deny"])
    view = wait_until(lambda: (v if any(t["question"] for t in v["tasks"]) else None)
                      if (v := service.view(run["workspace_id"], run["run_id"])) else None)
    task = view["tasks"][0]
    fields = {"task_id": task["task_id"], "generation": task["generation"], "native_id": task["native_id"],
              "request_id": "srq-permission", "result": {"choice": "once"}}
    act(service, run, "respond", "answer", **fields)
    act(service, run, "respond", "answer", **fields)
    assert len(worker.answers) == 1
    assert not any(c["operation"] == "respond" for c in service.runs.commands(run["run_id"]))
    act(service, run, "stop", "stop")
    wait_until(lambda: worker.executions[sent["session_id"]]["cancel_requested"])
    assert service.runs.get(run["run_id"])["phase"] == "stopping"
    complete(factory, status="interrupted")
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "paused")
    assert len(sends(factory)) == 1
