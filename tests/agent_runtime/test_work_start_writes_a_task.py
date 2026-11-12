"""``RT-WORK-START-WRITES-A-TASK-ROW``: New task, as Eternia sends it, saves a TASK.

Seen live 2026-11-12 (Eternia lane w1112b-work6, launcher row ``COMP-WORK-NEW-TASK-NOT-ON-THE-BOARD``): the Tasks
board's New task calls ``runtime.work.start`` with no ``group``; hermes appended a row with neither ``task:`` nor
``group:``, which the board (tasks only) never lists and which the writer's own task check refuses
(``ROW HAS NO TASK``) once the brain holds one task.

Every call here goes through ``serve_rpc.handle_request`` with the params Eternia's New task dialog sends
(``install_id``, ``owner``, ``client_scope``, ``request_id``, ``title``, ``body``, ``slot``, ``note``), against the
workspace's own Work brain and the real writer. The note the writer produced is then read by the vault's grammar
gate (``tests/tooling/test_work_queue_row_grammar.py::queue_rows``) and by ``tasks.task_defects``.

Killing mutations (each recorded red in the commit body):
* ``store.start`` passes no slug to ``_start_row`` → ``test_new_task_is_saved_as_a_task…``,
  ``test_a_second_new_task_lands…`` (the start is refused ``grammar_invalid``) and six more red;
* ``tasks.new_task_slug`` never adds the ID's tail on a clash → ``test_two_tasks_with_one_title…`` red (TWO TASKS);
* ``tasks.taken_slugs`` forgets groups → ``test_a_new_task_never_adopts…`` red;
* ``store.start`` skips ``task_title_refusal`` → ``test_a_title_the_task_rule_refuses…`` red (``grammar_invalid``
  from the writer instead of the plain words);
* ``_start_row`` writes ``task:`` beside a ``group`` → ``test_a_start_that_names_a_group…`` red;
* ``tasks.write_task_defects`` drops the carried-untasked arm → ``test_a_row_from_before…`` red.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from agent_runtime import paths
from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.serve_rpc import handle_request
from agent_runtime.serve_rpc.protocol import DEFERRED, RpcContext
from agent_runtime.store import WorkspaceStore
from agent_runtime.work_store import tasks
from agent_runtime.work_store.grammar import parse_note
from tests.tooling.test_work_queue_row_grammar import queue_rows

NOTE = "Work_Brain/20 — Active Initiatives/work-queue.md"


def rpc(method: str, params: dict) -> dict:
    """One request through the serve's own dispatch; a deferred reply is run here, as the serve's pool would."""

    jobs = []
    context = RpcContext(caller=STDIO_OWNER, spawn_reply=lambda job: jobs.append(job) or True)
    reply = handle_request({"jsonrpc": "2.0", "id": "1", "method": method, "params": params}, context)
    return jobs.pop()() if reply is DEFERRED else reply


@pytest.fixture
def desk():
    machine_roots_cache_clear()
    ws = WorkspaceStore().create(name="Desk").id
    surface = paths.office_surface_path(ws)
    surface.parent.mkdir(parents=True, exist_ok=True)
    surface.write_text("{}", encoding="utf-8")
    ensure_install_identity(paths.store_root())
    caps = rpc("runtime.work.capabilities", {})["result"]
    owner = next(row for row in caps["owners"] if row["workspace_id"] == ws)
    return SimpleNamespace(ws=ws, scope={"install_id": caps["install_id"], "owner": owner["owner"],
                                         "client_scope": "account"})


def new_task(desk, request_id: str, title: str, **more) -> dict:
    """``runtime.work.start`` as the New task dialog sends it: the board's default queue, no ``group``."""

    return rpc("runtime.work.start", {**desk.scope, "request_id": request_id, "title": title,
                                      "body": "What the user typed under Details.", "slot": "brain", "note": NOTE,
                                      **more})


def listed(desk) -> list[dict]:
    listing = rpc("runtime.work.list", desk.scope)["result"]
    return [row for board in listing["boards"] for queue in board["queues"] for row in queue["rows"]]


def brain_note(desk) -> str:
    """The queue note as the writer left it, read from the brain's own tip (not a working tree)."""

    return subprocess.run(["git", "-C", str(paths.default_brain_dir(desk.ws)), "show", f"HEAD:{NOTE}"], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def commit_row(desk, line: str) -> None:
    """Append ``line`` to the Work brain's queue as one commit in the brain itself (a row from an older build)."""

    root = paths.default_brain_dir(desk.ws)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "--", "."], check=True, capture_output=True)
    note = root / NOTE
    note.write_text(note.read_text(encoding="utf-8").rstrip("\n") + "\n" + line + "\n", encoding="utf-8", newline="\n")
    for args in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "row"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def gate_defects(desk) -> list[str]:
    """What the shared grammar says of the note the writer produced: the row gate's defects, then the task rules'."""

    text = brain_note(desk)
    rows = [f"{line_no}: {defect}" for line_no, _, defects in queue_rows(text) for defect in defects]
    return rows + tasks.task_defects(parse_note(text, slot="hermes", note=NOTE), [], siblings_visible=True)


def task_slugs(desk) -> dict[str, str | None]:
    return {row.title: row.task for row in parse_note(brain_note(desk), slot="brain", note=NOTE)}


def test_new_task_is_saved_as_a_task_and_listed_as_one(desk):
    reply = new_task(desk, "r1", "Plan the spring sale")
    task = reply["result"]["task"]
    assert " · task: plan-the-spring-sale · " in task["raw"] and task["group"] is None
    assert task["title"] == "Plan the spring sale" and task["status"] == "READY"
    assert task["body"] == "What the user typed under Details."
    assert [row["raw"] for row in listed(desk)] == [task["raw"]], "the board's read shows the same task row"
    assert task_slugs(desk) == {"Plan the spring sale": "plan-the-spring-sale"}
    assert gate_defects(desk) == []


def test_a_second_new_task_lands_in_a_brain_that_already_has_a_task(desk):
    """The live failure: with one task in the brain, the next New task was refused ``ROW HAS NO TASK``."""

    commit_row(desk, "- **`TASK-PILLS` — Pills on the board** · task: pills · READY 2026-11-09")
    for request, title in (("r1", "Plan the spring sale"), ("r2", "Write the welcome email")):
        reply = new_task(desk, request, title)
        assert "error" not in reply, reply
    assert task_slugs(desk) == {"Pills on the board": "pills", "Plan the spring sale": "plan-the-spring-sale",
                                "Write the welcome email": "write-the-welcome-email"}
    assert len(listed(desk)) == 3
    assert gate_defects(desk) == []


def test_two_tasks_with_one_title_are_two_tasks_with_their_own_slugs(desk):
    first = new_task(desk, "r1", "Call the dentist")["result"]["task"]
    second = new_task(desk, "r2", "Call the dentist")
    assert "error" not in second, second
    second = second["result"]["task"]
    tail = second["id"].rsplit("-", 1)[-1].lower()
    assert " · task: call-the-dentist · " in first["raw"]
    assert f" · task: call-the-dentist-{tail} · " in second["raw"]
    assert gate_defects(desk) == []
    replay = new_task(desk, "r2", "Call the dentist")["result"]
    assert replay["task"]["id"] == second["id"] and replay["receipt"]["replayed"] is True
    assert len(listed(desk)) == 2, "a replayed request adds no third task"


def test_a_new_task_never_adopts_the_subtasks_of_a_group_no_task_owns(desk):
    sub = new_task(desk, "r1", "First slice", group="pills.hermes")["result"]["task"]
    assert sub["group"] == "pills.hermes"
    task = new_task(desk, "r2", "Pills")["result"]["task"]
    tail = task["id"].rsplit("-", 1)[-1].lower()
    assert f" · task: pills-{tail} · " in task["raw"], "`pills` would have owned `pills.hermes`"


def test_a_start_that_names_a_group_still_adds_a_subtask(desk):
    task = new_task(desk, "r1", "Pills on the board")["result"]["task"]
    assert " · task: pills-on-the-board · " in task["raw"]
    sub = new_task(desk, "r2", "Draw the pill", group="pills-on-the-board")["result"]["task"]
    assert sub["raw"] == (f"- **`{sub['id']}` — Draw the pill** · group: pills-on-the-board · brief: "
                          f"`Work_Brain/50 — Agent Handoffs/work/{sub['id']}.md` · READY {sub['status_date']}")
    assert "task:" not in sub["raw"]
    assert gate_defects(desk) == []


@pytest.mark.parametrize(("title", "words"), [
    ("Fix the login/logout flow", "a path"),
    ("Close RT-WORK-START today", "a row ID"),
    ("word " * 21, "over 100"),
])
def test_a_title_the_task_rule_refuses_is_refused_in_plain_words_and_writes_nothing(desk, title, words):
    reply = new_task(desk, "r1", title)
    data = reply["error"]["data"]
    assert data["reason"] == "invalid_request"
    assert data["detail"].startswith("a task's title is plain English, and this one cannot be saved: ")
    assert words in data["detail"]
    assert listed(desk) == []
    sub = new_task(desk, "r2", title.strip(), group="pills")
    assert "error" not in sub, "a subtask's title is not held to the task-title rule"


@pytest.mark.parametrize("title", ["", "   "])
def test_an_empty_title_is_refused(desk, title):
    assert new_task(desk, "r1", title)["error"]["data"]["reason"] == "invalid_request"
    assert listed(desk) == []


def test_a_row_from_before_tasks_stays_writable_once_the_brain_holds_a_task(desk):
    """An older build's New task left rows with no task; the first real task must not lock them."""

    commit_row(desk, "- **`WORK-ABCDEF` — An older row** · READY 2026-11-09")
    assert "error" not in new_task(desk, "r1", "Plan the spring sale")
    moved = rpc("runtime.work.set_status", {**desk.scope, "request_id": "s1", "slot": "brain",
                                            "task_id": "WORK-ABCDEF", "status": "DEFERRED 2026-11-12: later"})
    assert "error" not in moved, moved
    assert moved["result"]["task"]["status_word"] == "DEFERRED"


def test_the_slug_is_whole_words_of_the_title_folded_to_ascii():
    assert tasks.new_task_slug("Réserver le café — à 9h!", "WORK-ABCDEF", ()) == "reserver-le-cafe-a-9h"
    long = tasks.new_task_slug("Reorganise everything in the warehouse before the inspection", "WORK-ABCDEF", ())
    assert long == "reorganise-everything-in-the-warehouse" and len(long) <= tasks.TASK_SLUG_LIMIT
    assert tasks.new_task_slug("日本語", "WORK-ABCDEF", ()) == "task-abcdef"
    assert tasks.new_task_slug("Pills", "WORK-ABCDEF", {"pills"}) == "pills-abcdef"
    assert tasks.new_task_slug("x" * 60, "WORK-ABCDEF", ()) == "x" * 40
