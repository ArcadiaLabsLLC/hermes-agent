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


def rows_of(listing):
    """The rows of a grouped ``runtime.work.list`` reply, board by board, queue by queue."""
    return [row for board in listing["boards"] for queue in board["queues"] for row in queue["rows"]]


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
    rows = rows_of(call(work, "list"))
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
    assert rows_of(call(work, "list")) == []


def test_operator_reference_is_the_assignee(work, monkeypatch):
    from agent_runtime import operator_conversation

    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", lambda reference: reference)
    reference = {"kind": "operator", "workspace_id": work.ws, "persona_id": "alice",
                 "persona_instance_id": "pi_alice_01", "session_id": "s1"}
    context = call(work, "context", conversation=reference)
    assert context["assignee"] == "persona:pi_alice_01" and context["can_start"] is True


def test_start_from_an_operator_conversation_assigns_and_takes_the_row_there(work, monkeypatch):
    """RT-WORK-START-CONVERSATION-LINK. Mutation: drop ``or here`` from ``start``'s assignee default
    -> the row has no assignee, no TAKEN mark, and ``in_conversation`` is False."""
    from agent_runtime import operator_conversation

    alice, bob = mint_free_floating("alice"), mint_free_floating("bob")
    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", lambda reference: reference)
    reference = {"kind": "operator", "workspace_id": work.ws, "persona_id": "alice",
                 "persona_instance_id": alice.id, "session_id": "s1"}
    task = start(work, "v1", conversation=reference)["task"]
    assert task["assignee"] == f"persona:{alice.id}" and task["status"] == "TAKEN"
    assert task["taken"]["persona_instance_id"] == alice.id and task["in_conversation"] is True
    listed = rows_of(call(work, "list", view="conversation", conversation=reference))
    assert [row["id"] for row in listed] == [task["id"]]
    # Started here but handed to someone else: assigned, not taken in this conversation.
    other = start(work, "v2", title="Hand off", conversation=reference, assignee=f"persona:{bob.id}")["task"]
    assert other["assignee"] == f"persona:{bob.id}" and other["status"] == "READY"
    assert other["taken"] is None and other["in_conversation"] is False


def test_unknown_caller_and_wrong_install_refuse(work):
    for operation in rpc.OPERATIONS:
        with pytest.raises(WorkRefused) as denied:
            service.execute(operation, work.scope, UNKNOWN_CALLER)
        assert denied.value.reason is Reason.DENIED
    for wrong in ({"install_id": "other"}, {"owner": "other"}):
        with pytest.raises(WorkRefused) as changed:
            call(work, "list", **wrong)
        assert changed.value.reason is Reason.OWNER_CHANGED
    assert rows_of(call(work, "list", LOCAL_CONSOLE)) == []


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
    assert {row["id"] for row in rows_of(call(work, "list", status="READY"))} == {plain, assigned}
    assert [row["id"] for row in rows_of(call(work, "list", assignee=f"persona:{alice.persona_id}"))] == [assigned]
    assert rows_of(call(work, "list", slot="elsewhere")) == []
    assert rows_of(call(work, "list", status="TAKEN")) == []


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


def test_list_groups_rows_per_brain_then_per_domain(work):
    task_id = start(work)["task"]["id"]
    (board,) = call(work, "list")["boards"]
    assert (board["slot"], board["label"], board["brain_dir"]) == ("brain", "Work", "Work_Brain/20 — Active Initiatives")
    (queue,) = board["queues"]
    assert (queue["note"], queue["program"], queue["title"]) == (
        "Work_Brain/20 — Active Initiatives/work-queue.md", "work", "Work queue")
    assert [(row["id"], row["slot"], row["program"]) for row in queue["rows"]] == [(task_id, "brain", "work")]
    assert "rows" not in call(work, "list")


def test_engine_rows_on_the_default_board_land_in_its_work_queue(work):
    import subprocess

    root = paths.default_brain_dir(work.ws)
    other = root / "Work_Brain" / "20 — Active Initiatives" / "alpha-queue.md"
    other.write_text("---\ntype: queue\nprogram: alpha\n---\n\n# Alpha\n", encoding="utf-8", newline="\n")
    for args in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "alpha"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    task = start(work)["task"]
    assert task["note"].endswith("/work-queue.md") and task["program"] == "work"
    (board,) = call(work, "list")["boards"]
    assert [(q["program"], q["title"]) for q in board["queues"]] == [("alpha", "Alpha"), ("work", "Work queue")]
