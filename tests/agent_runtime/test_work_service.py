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
    assert owner == {"owner": WorkScope(caps["install_id"], work.ws).owner, "workspace_id": work.ws,
                     "kind": "workspace", "label": "Desk",
                     "operations": ["inspect", "start", "edit", "assign", "claim", "release", "set_status", "move", "answer", "pull",
                                    "done", "close", "create_brain", "lend_skills"]}
    assert len({row["owner"] for row in caps["owners"]}) == len(caps["owners"])
    assert caps["default_brain"][work.ws] == {"state": "created", "reason": "needs_git_account"}
    assert (paths.default_brain_dir(work.ws) / ".git").is_dir()
    again = service.execute("capabilities", {}, STDIO_OWNER)
    assert again["default_brain"][work.ws] == {"state": "present", "reason": "needs_git_account"}


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


def test_move_drops_a_card_on_a_status_column(work):
    """RT-WORK-MOVE-ROW-COLUMN. Mutations: drop the RELEASE apply in ``store.move`` -> the TAKEN card stays
    TAKEN after a drop on DEFERRED, red; drop the revision check -> the stale drop writes, red; drop the
    ``unchanged`` early answer -> a same-column drop commits, red."""
    alice = mint_free_floating("alice")
    task = start(work)["task"]
    where = {"slot": "brain", "task_id": task["id"]}
    same = call(work, "move", request_id="m0", to="READY", **where)
    assert same["unchanged"] is True and same["receipt"] is None
    blocked = call(work, "move", request_id="m1", to="BLOCKED", reason="backend — `RT-X` first",
                   revision=task["revision"], **where)
    assert blocked["unchanged"] is False and blocked["task"]["status"] == "BLOCKED"
    assert blocked["task"]["status_body"] == "backend — `RT-X` first"
    with pytest.raises(WorkRefused) as stale:
        call(work, "move", request_id="m2", to="READY", revision=task["revision"], **where)
    assert stale.value.reason is Reason.ROW_CHANGED and stale.value.data["task"]["status"] == "BLOCKED"
    call(work, "claim", request_id="c1", who=f"persona:{alice.id}", **where)
    moved = call(work, "move", request_id="m3", to="DEFERRED", **where)["task"]
    assert moved["status"] == "DEFERRED" and moved["taken"] is None
    for bad, reason in (({"to": "TAKEN"}, Reason.INVALID), ({"to": "BLOCKED"}, Reason.GRAMMAR_INVALID),
                        ({"to": "BLOCKED", "reason": "because"}, Reason.GRAMMAR_INVALID)):
        with pytest.raises(WorkRefused) as refused:
            call(work, "move", request_id="m9", **bad, **where)
        assert refused.value.reason is reason


def test_move_drops_a_card_on_live_check_and_on_decision_and_the_question_is_answered(work):
    """RT-QUEUE-LIVE-CHECK-STATUS. Mutations: drop the question check in ``store.move`` -> a DECISION drop with no
    question writes, red; drop ``LIVE CHECK|DECISION`` from ``grammar.STATUS`` -> ``to`` refuses ``invalid``, red."""
    task = start(work)["task"]
    where = {"slot": "brain", "task_id": task["id"]}
    live = call(work, "move", request_id="v1", to="LIVE CHECK", reason="open the board, read the pill", **where)["task"]
    assert (live["status"], live["status_body"]) == ("LIVE CHECK", "open the board, read the pill")
    with pytest.raises(WorkRefused) as unasked:
        call(work, "move", request_id="v2", to="DECISION", **where)
    assert unasked.value.reason is Reason.GRAMMAR_INVALID
    asked = call(work, "move", request_id="v3", to="DECISION", reason="round or square?", **where)["task"]
    assert (asked["status"], asked["status_body"]) == ("DECISION", "round or square?")
    answered = call(work, "answer", request_id="v4", answer="round", line=asked["raw"], **where)["task"]
    assert answered["status"] == "READY" and answered["rulings"][-1].endswith(": owner — round")
    kept = call(work, "set_status", request_id="v5", status="LIVE CHECK 2026-11-12: read the pill", **where)["task"]
    assert kept["status"] == "LIVE CHECK"


def test_move_guards_on_the_line_the_board_drew(work):
    """RT-WORK-MOVE-LINE-GUARD: a board reading the user's checkout holds the row's raw line, not ``revision``.
    Mutation: drop the ``line`` check in ``store.move`` -> the stale-line drop writes BLOCKED, red."""
    task = start(work)["task"]
    where = {"slot": "brain", "task_id": task["id"]}
    with pytest.raises(WorkRefused) as stale:
        call(work, "move", request_id="l0", to="DEFERRED", line=task["raw"].replace("READY", "BLOCKED"), **where)
    assert stale.value.reason is Reason.ROW_CHANGED and stale.value.data["task"]["raw"] == task["raw"]
    assert rows_of(call(work, "list"))[0]["status"] == "READY"
    moved = call(work, "move", request_id="l1", to="DEFERRED", line=task["raw"] + "\r", **where)
    assert moved["unchanged"] is False and moved["task"]["status"] == "DEFERRED"
    with pytest.raises(WorkRefused) as behind:
        call(work, "move", request_id="l2", to="READY", line=task["raw"], **where)
    assert behind.value.reason is Reason.ROW_CHANGED and behind.value.data["task"]["status"] == "DEFERRED"
    with pytest.raises(WorkRefused) as bad:
        call(work, "move", request_id="l3", to="READY", line=7, **where)
    assert bad.value.reason is Reason.INVALID


def _owner_decision(work, request_id="q0"):
    task = start(work)["task"]
    where = {"slot": "brain", "task_id": task["id"]}
    asked = call(work, "set_status", request_id=request_id,
                 status="BLOCKED 2026-11-08: owner decision — ship it? · Recommend: yes", **where)["task"]
    return asked, where


def test_answer_rules_an_owner_decision_and_readies_the_row(work):
    """RT-WORK-ANSWER-VERB. Mutations: drop the RULED segment in ``grammar._answer`` -> no ruling on the row, red;
    drop the owner-decision check -> answering a READY row writes, red; drop the gate in ``store._guarded_write``
    -> the stale-line answer writes, red."""
    asked, where = _owner_decision(work)
    with pytest.raises(WorkRefused) as stale:
        call(work, "answer", request_id="a0", answer="yes", line=asked["raw"].replace("ship", "drop"), **where)
    assert stale.value.reason is Reason.ROW_CHANGED and stale.value.data["task"]["raw"] == asked["raw"]
    with pytest.raises(WorkRefused) as unguarded:
        call(work, "answer", request_id="a1", answer="yes", **where)
    assert unguarded.value.reason is Reason.INVALID
    answered = call(work, "answer", request_id="a2", answer="yes, ship `it` today", line=asked["raw"] + "\r",
                    **where)["task"]
    assert answered["status"] == "READY" and answered["recommend"] is None
    day = answered["status_date"]
    assert answered["rulings"] == [f"RULED {day}: owner — yes, ship -it- today"]
    assert answered["raw"].endswith(f" · RULED {day}: owner — yes, ship -it- today · READY {day}")
    with pytest.raises(WorkRefused) as ready:
        call(work, "answer", request_id="a3", answer="no", line=answered["raw"], **where)
    assert ready.value.reason is Reason.INVALID and "owner decision" in ready.value.detail


def test_close_archives_a_row_with_the_owners_outcome(work):
    """RT-WORK-OWNER-CLOSE-VERB. Mutations: write ``DONE`` for ``CLOSED`` in ``store.close`` -> the outcome reads
    DONE here, red; drop the gate in ``store._guarded_write`` -> the stale-line close archives, red."""
    alice = mint_free_floating("alice")
    task = start(work)["task"]
    where = {"slot": "brain", "task_id": task["id"]}
    claimed = call(work, "claim", request_id="c1", who=f"persona:{alice.id}", **where)["task"]
    with pytest.raises(WorkRefused) as stale:
        call(work, "close", request_id="x0", line=task["raw"], **where)
    assert stale.value.reason is Reason.ROW_CHANGED and stale.value.data["task"]["status"] == "TAKEN"
    closed = call(work, "close", request_id="x1", line=claimed["raw"], result="Done by hand.", **where)
    ending = closed["ending"]
    assert ending["outcome"] == "CLOSED" and ending["words"] == "done" and ending["result"] == "Done by hand."
    assert ending["archive_note"].endswith(f"-{ending['date'][:7]}.md") and closed["receipt"]["commit"]
    assert rows_of(call(work, "list")) == []
    assert call(work, "inspect", slot="brain", task_id=task["id"])["ending"]["outcome"] == "CLOSED"
    other = start(work, request_id="request-2", title="Other")["task"]
    worded = call(work, "close", request_id="x2", slot="brain", task_id=other["id"], line=other["raw"],
                  words="not needed any more")["ending"]
    assert worded["words"] == "not needed any more" and worded["result"] in ("", None)


def test_pull_refuses_an_unbound_slot(work):
    with pytest.raises(WorkRefused) as refused:
        call(work, "pull", request_id="p1", slot="nowhere")
    assert refused.value.reason is Reason.SLOT_UNBOUND


def test_operator_reference_is_the_assignee(work, monkeypatch):
    from agent_runtime import operator_conversation

    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", lambda reference: reference)
    reference = {"kind": "operator", "workspace_id": work.ws, "persona_id": "alice",
                 "persona_instance_id": "pi_alice_01", "session_id": "s1"}
    context = call(work, "context", conversation=reference)
    assert context["assignee"] == "persona:pi_alice_01" and context["can_start"] is True


def test_start_from_a_conversation_assigns_and_never_claims(work, monkeypatch):
    """RT-WORK-START-NEVER-CLAIMS (owner ruling 2026-11-02: adding a task never claims it, from a chat
    or anywhere). Mutations: restore ``taken_by = here`` in ``start`` (and its mark in ``_start_row``)
    -> the line carries ``**TAKEN`` and the task is TAKEN, red; drop ``or here`` from the assignee
    default -> the row has no assignee, red."""
    from agent_runtime import operator_conversation

    alice, bob = mint_free_floating("alice"), mint_free_floating("bob")
    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", lambda reference: reference)
    reference = {"kind": "operator", "workspace_id": work.ws, "persona_id": "alice",
                 "persona_instance_id": alice.id, "session_id": "s1"}
    task = start(work, "v1", conversation=reference)["task"]
    assert task["assignee"] == f"persona:{alice.id}" and task["status"] == "READY"
    assert task["taken"] is None and task["in_conversation"] is False
    line = call(work, "inspect", slot="brain", task_id=task["id"])["task"]["raw"]
    assert f"assignee: persona:{alice.id}" in line and " · READY " in line and "**TAKEN" not in line
    # Nothing runs it: the conversation's view holds only rows taken there.
    assert rows_of(call(work, "list", view="conversation", conversation=reference)) == []
    # Taking it is its own explicit choice.
    claimed = call(work, "claim", request_id="v1c", slot="brain", task_id=task["id"],
                   conversation=reference)["task"]
    assert claimed["status"] == "TAKEN" and claimed["in_conversation"] is True
    listed = rows_of(call(work, "list", view="conversation", conversation=reference))
    assert [row["id"] for row in listed] == [task["id"]]
    # Started here but handed to someone else: assigned, not taken.
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
    assert gone["task"] is None and gone["ending"]["subject"].startswith(f"work: close {task_id} operator")


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


def test_lend_skills_unions_and_revoke_differences_through_the_writer(work, monkeypatch):
    """p10-work S1: ``runtime.work.lend_skills`` rewrites the row's ``skills:`` segment; an unloadable skill
    refuses the whole lend ``skills_not_loadable`` with ``rejected_skills`` and nothing written."""

    from agent_runtime.chat_verbs import queue_skill

    monkeypatch.setattr(queue_skill, "_rejected_skills",
                        lambda skills: {s: "not_found" for s in skills if s.startswith("ghost")})
    task_id = start(work)["task"]["id"]
    where = {"slot": "brain", "task_id": task_id}
    lent = call(work, "lend_skills", request_id="l1", skills=["git-workflow", "eternia/qa"], **where)
    assert lent["task"]["skills"] == ["git-workflow", "eternia/qa"] and lent["receipt"]["kind"] == "work.row_set_skills"
    more = call(work, "lend_skills", request_id="l2", skills=["eternia/qa", "pytest"], mode="lend", **where)["task"]
    assert more["skills"] == ["git-workflow", "eternia/qa", "pytest"] and more["raw"].count("skills:") == 1
    less = call(work, "lend_skills", request_id="l3", skills=["git-workflow", "pytest"], mode="revoke", **where)["task"]
    assert less["skills"] == ["eternia/qa"]
    reply = rpc._work_reply("r", "lend_skills", {**work.scope, "request_id": "l4", "skills": ["ghost-1"], **where},
                            STDIO_OWNER)
    assert reply["error"]["data"] == {"reason": "skills_not_loadable", "detail": "ghost-1",
                                      "rejected_skills": {"ghost-1": "not_found"}}
    gone = call(work, "lend_skills", request_id="l5", skills=["eternia/qa"], mode="revoke", **where)["task"]
    assert gone["skills"] == [] and "skills:" not in gone["raw"]
    with pytest.raises(WorkRefused) as bad:
        call(work, "lend_skills", request_id="l6", skills=["x"], mode="borrow", **where)
    assert bad.value.reason is Reason.INVALID


# ── the general todo: the personal board and the agent view (plan general-todo-2026-10-25 §2.2) ──


def _personal(work):
    owner = next(row for row in work.caps["owners"] if row["kind"] == "personal")
    return SimpleNamespace(scope={**work.scope, "owner": owner["owner"]}, owner=owner)


def test_the_personal_board_is_one_more_owner_with_its_own_machine_local_brain(work):
    """RT-GENERAL-TODO-G1. Mutation: drop the personal scope from ``service.scopes`` -> no ``personal``
    owner in ``capabilities`` and a personal-owner call refuses ``work_owner_changed``."""
    caps = work.caps
    assert caps["board_kinds"] == ["workspace", "personal", "agent"]
    personal = _personal(work)
    assert personal.owner["workspace_id"] == "personal" and personal.owner["label"] == "Personal"
    assert personal.owner["owner"] not in {row["owner"] for row in caps["owners"] if row["kind"] == "workspace"}
    assert caps["personal_board"] == {"state": "created"}
    assert (paths.default_brain_dir("personal") / ".git").is_dir()
    assert service.execute("capabilities", {}, STDIO_OWNER)["personal_board"] == {"state": "present"}
    task = service.execute("start", {**personal.scope, "request_id": "p1", "title": "Call the dentist"},
                           STDIO_OWNER)["task"]
    listed = service.execute("list", {**personal.scope, "kind": "personal"}, STDIO_OWNER)
    assert [row["id"] for row in rows_of(listed)] == [task["id"]]
    assert rows_of(call(work, "list")) == []  # the workspace's board never sees the personal row
    with pytest.raises(WorkRefused) as wrong_kind:
        service.execute("list", {**personal.scope, "kind": "workspace"}, STDIO_OWNER)
    assert wrong_kind.value.reason is Reason.INVALID


def test_the_personal_board_is_never_promoted_to_a_remote(work, monkeypatch):
    """Machine-local by contract, even on a machine whose GitHub account answers. Mutation: drop the
    ``PERSONAL_BOARD_ID`` refusal in ``default_brain.promote_default_brain`` -> a private repo is created
    for it (the ``_auto_promote`` guard is the cheap early exit in front of it)."""
    from agent_runtime import git_host_account
    from agent_runtime.work_store import default_brain

    created = []
    monkeypatch.setattr(git_host_account, "connected_github", lambda *a, **k: object())
    monkeypatch.setattr(git_host_account, "create_private_repo",
                        lambda account, name: created.append(name) or "https://example.invalid/r.git")
    default_brain.ensure_default_brain("personal", issued_at="2026-10-26T00:00:00")
    assert created == []
    with pytest.raises(WorkRefused) as refused:
        default_brain.promote_default_brain("personal", issued_at="2026-10-26T00:00:00")
    assert refused.value.reason is Reason.INVALID and created == []


def test_an_agents_todo_is_a_view_over_every_board_it_can_see(work):
    """RT-GENERAL-TODO-G2. Rows assigned to the instance OR its persona, on its workspace's boards and the
    personal board; another agent's rows never. Mutation: drop ``instance.persona_id`` from the tokens in
    ``service._agent_reach`` -> the persona-assigned row leaves the view."""
    from agent_runtime.persona_assignments import PersonaInstanceStore

    alice, bob = mint_free_floating("alice"), mint_free_floating("bob")
    personal = _personal(work)
    on_ws = start(work, "a1", title="Workspace task", assignee=f"persona:{alice.id}")["task"]["id"]
    to_persona = start(work, "a2", title="Any alice", assignee=f"persona:{alice.persona_id}")["task"]["id"]
    start(work, "b1", title="Bob task", assignee=f"persona:{bob.id}")
    start(work, "n1", title="Nobody")
    mine = service.execute("start", {**personal.scope, "request_id": "a3", "title": "Personal for alice",
                                     "assignee": f"persona:{alice.id}"}, STDIO_OWNER)["task"]["id"]
    view = service.execute("list", {**work.scope, "kind": "agent", "assignee": f"persona:{alice.id}"}, STDIO_OWNER)
    assert view["kind"] == "agent" and view["assignee"] == f"persona:{alice.id}"
    assert set(view["assignees"]) == {alice.id, alice.persona_id}
    ids = {row["id"] for owner in view["owners"] for board in owner["boards"] for queue in board["queues"]
           for row in queue["rows"]}
    assert ids == {on_ws, to_persona, mine}
    assert {owner["kind"] for owner in view["owners"]} == {"workspace", "personal"}
    # Placed in ANOTHER workspace, an instance sees only that workspace's boards and the personal one. A
    # placement, not the canonical channel: a canonical carries no workspace (RT-GLOBAL-SINGLETON-CANONICAL).
    elsewhere = PersonaInstanceStore().add_instance(
        persona_id=alice.persona_id, placement_id=f"{alice.persona_id}_agent_2", workspace_id="ws_elsewhere")
    placed = service.execute("list", {**work.scope, "kind": "agent", "assignee": f"persona:{elsewhere.id}"},
                             STDIO_OWNER)
    assert [owner["kind"] for owner in placed["owners"]] == ["personal"]
    with pytest.raises(WorkRefused) as no_one:
        service.execute("list", {**work.scope, "kind": "agent"}, STDIO_OWNER)
    assert no_one.value.reason is Reason.INVALID


def test_list_reads_a_notes_commit_time_once_not_once_per_row(work, monkeypatch):
    # RT-WORK-LIST-OWNER-SIZE-5S: a `git log` per ROW was ~5 s on a 622-row board; every row of a
    # note shares the note's commit time, so the list asks once per note (plus the board's own).
    from agent_runtime.work_store.writer import Writer

    ids = [start(work, f"q{n}", title=f"Row {n}")["task"]["id"] for n in range(4)]
    asked = []
    real = Writer.note_committed_at
    monkeypatch.setattr(Writer, "note_committed_at", lambda self, note: asked.append(note) or real(self, note))
    listed = call(work, "list")
    (board,) = listed["boards"]
    (queue,) = board["queues"]
    assert [row["id"] for row in queue["rows"]] == ids
    assert sorted(asked) == sorted([board["brain_dir"], queue["note"]])
    inspected = call(work, "inspect", slot="brain", task_id=ids[0])["task"]
    assert {row["updated_at"] for row in queue["rows"]} == {inspected["updated_at"]} != {None}
    assert queue["rows"][0]["revision"] == next(
        row for row in rows_of(call(work, "list", status="READY")) if row["id"] == ids[0])["revision"]


def _commit_row(work, line):
    """Append ``line`` to the default brain's work queue as one commit in the brain itself (a teammate's push)."""
    import subprocess

    root = paths.default_brain_dir(work.ws)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "--", "."], check=True, capture_output=True)
    note = root / "Work_Brain" / "20 — Active Initiatives" / "work-queue.md"
    note.write_text(note.read_text(encoding="utf-8").rstrip("\n") + "\n" + line + "\n", encoding="utf-8", newline="\n")
    for args in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "row"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_claim_refuses_a_subtask_whose_task_is_not_ready(work):
    """RT-QUEUE-TASKS-GRAMMAR (launcher plan QUEUE_TASKS_AND_SUBTASKS_2026-11-09 D3). KILLING MUTATIONS: drop the
    ``task.status is not Status.READY`` raise in ``store.parent_task`` -> the DEFERRED task's subtask is claimed,
    red; drop the ``gate`` call in ``_row_write`` -> the same, red."""
    alice = mint_free_floating("alice")
    sub = start(work, request_id="sub", group="pills.hermes")["task"]["id"]
    where = {"slot": "brain", "task_id": sub}
    lone = call(work, "claim", request_id="c0", who=f"persona:{alice.id}", **where)
    assert lone["task"]["status"] == "TAKEN"
    assert lone["parent_task"]["checked"] is False and "no visible brain has a task for `pills.hermes`" in (
        lone["parent_task"]["detail"])
    call(work, "release", request_id="r0", **where)
    _commit_row(work, "- **`TASK-PILLS` — Pills on the board** · task: pills · DEFERRED 2026-11-09: after release")
    with pytest.raises(WorkRefused) as refused:
        call(work, "claim", request_id="c1", who=f"persona:{alice.id}", **where)
    assert refused.value.reason is Reason.TASK_NOT_READY and "`TASK-PILLS`" in refused.value.detail
    assert refused.value.data == {"task_id": "TASK-PILLS", "task_status": "DEFERRED"}
    call(work, "set_status", request_id="s1", status="READY 2026-11-09", slot="brain", task_id="TASK-PILLS")
    claimed = call(work, "claim", request_id="c2", who=f"persona:{alice.id}", **where)
    assert claimed["task"]["status"] == "TAKEN"
    assert claimed["parent_task"] == {"group": "pills.hermes", "task_id": "TASK-PILLS", "task_status": "READY",
                                      "checked": True}
    task = call(work, "claim", request_id="c3", who=f"persona:{alice.id}", slot="brain", task_id="TASK-PILLS")
    assert task["parent_task"] is None, "a task row is not a subtask"


# ── RT-WORK-CLAIM-RUNS-UNTIL-DONE ──


def test_capabilities_say_a_run_can_keep_going_until_done(work):
    assert work.caps["until_done_runs"] is True and work.caps["until_done_max_passes"] == 20


def test_a_claim_keeps_the_goal_mode_it_asked_for_and_refuses_an_unknown_one(work):
    """Killing mutation: ``store.claim`` never calls ``until_done.keep`` → the kept mode reads ``none``, red."""

    from agent_runtime.work_store import until_done
    from agent_runtime.work_store.executor import GoalMode
    from agent_runtime.work_store.grammar import RowRef

    alice = mint_free_floating("alice")
    task = start(work)["task"]
    where = {"slot": task["slot"], "task_id": task["id"]}
    who = f"persona:{alice.id}"
    with pytest.raises(WorkRefused) as refused:
        call(work, "claim", request_id="c0", who=who, goal_mode="forever", **where)
    assert refused.value.reason is Reason.GOAL_MODE_UNSUPPORTED
    assert call(work, "list")["boards"][0]["queues"][0]["rows"][0]["status"] == "READY", "refused before any write"
    claimed = call(work, "claim", request_id="c1", who=who, goal_mode="until_done", **where)
    assert claimed["goal_mode"] == "until_done" and claimed["task"]["status"] == "TAKEN"
    ref = RowRef(task["slot"], claimed["receipt"]["ref"]["note"], task["id"])
    assert until_done.kept(work.ws, ref, who) is GoalMode.UNTIL_DONE
    call(work, "release", request_id="r1", who=who, **where)
    assert until_done.kept(work.ws, ref, who) is GoalMode.NONE, "a release forgets it"
    plain = call(work, "claim", request_id="c2", who=who, **where)
    assert plain["goal_mode"] == "none" and until_done.kept(work.ws, ref, who) is GoalMode.NONE
