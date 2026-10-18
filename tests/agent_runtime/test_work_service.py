"""runtime.work.* over a workspace's todo board: owners are workspaces, tasks are brain queue rows,
every write is one git commit through the Work writer (plan ``work-on-markdown-2026-10-18.md`` §6.2).

The workspace here binds no repo, so ``capabilities`` gives it the local default brain and every
write lands there (steps 2 and 8 of §5 are the local tip and the compare-and-swap).
"""
from types import SimpleNamespace

import pytest

from agent_runtime import paths
from agent_runtime.call_authorization import LOCAL_CONSOLE, STDIO_OWNER, UNKNOWN_CALLER
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import WorkspaceStore
from agent_runtime.work import rpc, service
from agent_runtime.work.model import Reason, WorkRefused, WorkScope
from agent_runtime.work_store.grammar import WORK_ID
from tests.agent_runtime.persona_instance_mint import mint_free_floating


@pytest.fixture
def work():
    machine_roots_cache_clear()
    ws = WorkspaceStore().create(name="Desk").id
    surface = paths.office_surface_path(ws)
    surface.parent.mkdir(parents=True, exist_ok=True)
    surface.write_text("{}", encoding="utf-8")
    ensure_install_identity(paths.store_root())
    caps = service.execute("capabilities", {}, STDIO_OWNER)
    owner = next(row for row in caps["owners"] if row["workspace_id"] == ws)
    scope = {"install_id": caps["install_id"], "owner": owner["owner"], "client_scope": "account"}
    return SimpleNamespace(ws=ws, caps=caps, scope=scope)


def call(work, operation, caller=STDIO_OWNER, **params):
    return service.execute(operation, {**work.scope, **params}, caller)


def start(work, request_id="request-1", **overrides):
    return call(work, "start", **{"request_id": request_id, "title": "Review", "body": "Review the change.", **overrides})


def test_capabilities_lists_one_owner_per_workspace_and_creates_the_default_brain(work):
    caps = work.caps
    assert caps["version"] == 2 and caps["chat_scopes"] is True
    owner = next(row for row in caps["owners"] if row["workspace_id"] == work.ws)
    assert owner == {"owner": WorkScope(caps["install_id"], work.ws).owner, "workspace_id": work.ws, "label": "Desk",
                     "operations": ["inspect", "start", "assign", "claim", "release", "set_status", "done",
                                    "create_brain"]}
    assert len({row["owner"] for row in caps["owners"]}) == len(caps["owners"])
    assert caps["default_brain"][work.ws] == {"state": "created"}
    assert (paths.default_brain_dir(work.ws) / ".git").is_dir()
    again = service.execute("capabilities", {}, STDIO_OWNER)
    assert again["default_brain"][work.ws] == {"state": "present"}


def test_start_mints_a_work_id_and_replays_by_request_id(work):
    first = start(work)
    task = first["task"]
    assert WORK_ID.match(task["id"]) and task["status"] == "READY" and task["slot"] == "brain"
    assert task["body"] == "Review the change." and task["pointers"][0].endswith(f"/work/{task['id']}.md")
    assert first["disposition"] == "accepted" and first["receipt"]["kind"] == "work.row_append"
    again = start(work)
    assert again["task"]["id"] == task["id"] and again["receipt"]["replayed"] is True
    rows = call(work, "list")["rows"]
    assert [row["id"] for row in rows] == [task["id"]]


def test_claim_release_set_status_done_through_the_writer(work):
    alice = mint_free_floating("alice")
    task_id = start(work)["task"]["id"]
    where = {"slot": "brain", "task_id": task_id}
    claimed = call(work, "claim", request_id="c1", who=f"persona:{alice.id}", **where)["task"]
    assert claimed["status"] == "TAKEN" and claimed["taken"]["persona_instance_id"] == alice.id
    released = call(work, "release", request_id="r1", status="DEFERRED 2026-10-18: stopped — test", **where)["task"]
    assert released["status"] == "DEFERRED" and released["taken"] is None
    assert call(work, "set_status", request_id="s1", status="READY 2026-10-18", **where)["task"]["status"] == "READY"
    call(work, "claim", request_id="c2", who=f"persona:{alice.id}", **where)
    ending = call(work, "done", request_id="d1", result="Shipped the review.", **where)["ending"]
    assert "result: Shipped the review." in ending["body"]
    assert call(work, "list")["rows"] == []


def test_operator_reference_is_the_assignee(work, monkeypatch):
    from agent_runtime import operator_conversation

    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", lambda reference: reference)
    reference = {"kind": "operator", "workspace_id": work.ws, "persona_id": "alice",
                 "persona_instance_id": "pi_alice_01", "session_id": "s1"}
    context = call(work, "context", conversation=reference)
    assert context["assignee"] == "persona:pi_alice_01" and context["can_start"] is True


def test_unknown_caller_and_wrong_install_refuse(work):
    for operation in rpc.OPERATIONS:
        with pytest.raises(WorkRefused) as denied:
            service.execute(operation, work.scope, UNKNOWN_CALLER)
        assert denied.value.reason is Reason.DENIED
    for wrong in ({"install_id": "other"}, {"owner": "other"}):
        with pytest.raises(WorkRefused) as changed:
            call(work, "list", **wrong)
        assert changed.value.reason is Reason.OWNER_CHANGED
    assert call(work, "list", LOCAL_CONSOLE)["rows"] == []


def test_inspect_of_a_gone_row_carries_its_ending(work):
    task_id = start(work)["task"]["id"]
    where = {"slot": "brain", "task_id": task_id}
    assert call(work, "inspect", **where)["task"]["id"] == task_id
    call(work, "done", request_id="d1", result="Nothing left.", **where)
    gone = call(work, "inspect", **where)
    assert gone["task"] is None and gone["ending"]["subject"].startswith(f"work: delete {task_id} operator")


def test_list_filters_slot_status_assignee(work):
    alice = mint_free_floating("alice")
    plain = start(work, "q1", title="Plain")["task"]["id"]
    assigned = start(work, "q2", title="Assigned", assignee=f"persona:{alice.persona_id}")["task"]["id"]
    listed = call(work, "list")
    assert {board["slot"]: (board["is_default"], board["local"]) for board in listed["boards"]} == {"brain": (True, True)}
    assert {row["id"] for row in call(work, "list", status="READY")["rows"]} == {plain, assigned}
    assert [row["id"] for row in call(work, "list", assignee=f"persona:{alice.persona_id}")["rows"]] == [assigned]
    assert call(work, "list", slot="elsewhere")["rows"] == []
    assert call(work, "list", status="TAKEN")["rows"] == []


def test_refusals_are_typed_and_leak_nothing(work):
    task_id = start(work)["task"]["id"]
    where = {"slot": "brain", "task_id": task_id}
    with pytest.raises(WorkRefused) as unknown:
        call(work, "claim", request_id="c1", who="persona:pi_nobody", **where)
    assert unknown.value.reason is Reason.ASSIGNEE_UNKNOWN
    alice = mint_free_floating("alice")
    call(work, "claim", request_id="c2", who=f"persona:{alice.id}", **where)
    reply = rpc._work_reply("r", "claim", {**work.scope, "request_id": "c3", "who": f"persona:{alice.id}", **where},
                            STDIO_OWNER)
    assert reply["error"]["data"] == {"reason": "already_taken", "detail": f"persona:{alice.id}"}
    with pytest.raises(WorkRefused) as titled:
        start(work, "q9", title="has `code`")
    assert titled.value.reason is Reason.INVALID
    with pytest.raises(WorkRefused) as gone:
        call(work, "set_status", request_id="s1", status="READY 2026-10-18", slot="brain", task_id="WORK-ZZZZZZ")
    assert gone.value.reason is Reason.ROW_GONE


def test_git_switched_off_refuses_git_unavailable(work, monkeypatch):
    monkeypatch.setattr(service, "git_shipped", lambda: False)
    with pytest.raises(WorkRefused) as refused:
        call(work, "list")
    assert refused.value.reason is Reason.GIT_UNAVAILABLE
    fresh = WorkspaceStore().create(name="Fresh").id
    surface = paths.office_surface_path(fresh)
    surface.parent.mkdir(parents=True, exist_ok=True)
    surface.write_text("{}", encoding="utf-8")
    caps = service.execute("capabilities", {}, STDIO_OWNER)
    assert caps["default_brain"][fresh] == {"state": "unavailable", "reason": "git_unavailable"}
    assert not paths.default_brain_dir(fresh).exists()
