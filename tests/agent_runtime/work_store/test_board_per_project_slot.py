"""RT-WORK-BOARD-PER-PROJECT-SLOT: every live slot of every Project is a board, keyed by ``(project, slot)``.

Launcher plan workspace-todo-all-projects-2026-10-31 (`EterniaLauncher/docs/mission_control/planned/`),
H1–H4 and §5. Two Projects, ``Alpha`` (p1) and ``Beta`` (p2), each declare a slot named ``launcher``;
by default each over its own repository (a bare origin and a clone bound here), and in the merge
test over ONE checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from hermes_time import now

from agent_runtime import paths
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.project_categories import board_slots
from agent_runtime.project_store import ProjectStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.work import store as work_store
from agent_runtime.work_store.board import declared_boards, pick
from agent_runtime.work_store.engine import RecordState, RunRecord
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import bind_project

T0 = "2026-10-31T10:00:00+00:00"
NOTE = "Launcher_Brain/20 — Active Initiatives/q.md"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _repo(tmp_path: Path, name: str, row_id: str) -> SimpleNamespace:
    origin = tmp_path / f"{name}.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    clone = tmp_path / name
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    (clone / NOTE).parent.mkdir(parents=True)
    (clone / NOTE).write_text(HEAD + f"- **`{row_id}` — a row** · READY 2026-10-31\n", encoding="utf-8", newline="\n")
    git("add", "-A", cwd=clone)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    return SimpleNamespace(origin=origin, clone=clone, url=f"https://example.com/{name}.git")


def _project(workspace: str, project_id: str, name: str, repo: SimpleNamespace, *, revision: int,
             slots: tuple[str, ...] = ("launcher",)) -> None:
    ProjectStore().declare(project_id, [{"name": slot, "repo": {"clone_url": repo.url, "default_branch": "main"}}
                                        for slot in slots], issued_at=T0, machine="m", name=name)
    for slot in slots:
        bind_project(project_id, slot, str(repo.clone), issued_at=T0)
    set_project_connection(workspace, project_id, connected=True, expected_revision=revision)


@pytest.fixture
def two(tmp_path: Path, workspace: str) -> SimpleNamespace:
    alpha, beta = _repo(tmp_path, "alpha", "AL-1"), _repo(tmp_path, "beta", "BE-1")
    _project(workspace, "p1", "Alpha", alpha, revision=0)
    _project(workspace, "p2", "Beta", beta, revision=1)
    return SimpleNamespace(ws=workspace, alpha=alpha, beta=beta, scope=SimpleNamespace(workspace_id=workspace))


def _instance(workspace: str) -> None:
    PersonaInstanceStore()._write(PersonaInstance(
        id="personainst_a", persona_id="dev", role="dev", display_name="a", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace, updated_at=now()))


def test_a_project_with_a_boards_category_lists_every_slot(tmp_path, workspace):
    """Mutation: restore the ``name != chosen: continue`` arm in ``board_slots`` -> only ``launcher`` lists."""
    repo = _repo(tmp_path, "alpha", "AL-1")
    _project(workspace, "p1", "Alpha", repo, revision=0, slots=("backend", "launcher"))
    ProjectStore().set_category("p1", "boards", slot="launcher", subpath=None, shared=True, issued_at=T0)
    assert [(s.slot, s.project_default) for s in board_slots(workspace)] == [("backend", False), ("launcher", True)]


def test_one_name_over_two_repositories_is_two_boards_keyed_by_project(two):
    """Mutation: key ``_merged`` by slot alone (``_same_repo`` -> True) -> one board."""
    found = declared_boards(two.ws)
    assert [(b.key, b.project_name, b.checkout) for b in found] == [
        ("p1/launcher", "Alpha", two.alpha.clone), ("p2/launcher", "Beta", two.beta.clone)]


def test_one_name_over_one_checkout_is_one_board_naming_both_projects(tmp_path, workspace):
    """Mutation: drop the merge (``_merged`` returns ``found``) -> two boards."""
    repo = _repo(tmp_path, "alpha", "AL-1")
    _project(workspace, "p1", "Alpha", repo, revision=0)
    _project(workspace, "p2", "Beta", repo, revision=1)
    (board,) = declared_boards(workspace)
    assert board.projects == (("p1", "Alpha"), ("p2", "Beta"))
    assert pick([board], "launcher", "p2") is board


def test_the_wire_carries_the_owner_and_this_machines_checkout(two):
    """Mutation: remove ``project_id`` (or ``project_name`` / ``checkout``) from ``board_wire`` -> red."""
    listing = work_store.list_work(two.scope, {})
    wire = [(b["slot"], b["project_id"], b["project_name"], b["checkout"], b["projects"]) for b in listing["boards"]]
    assert wire == [
        ("launcher", "p1", "Alpha", str(two.alpha.clone), [{"project_id": "p1", "project_name": "Alpha"}]),
        ("launcher", "p2", "Beta", str(two.beta.clone), [{"project_id": "p2", "project_name": "Beta"}])]
    (row,) = listing["boards"][1]["queues"][0]["rows"]
    assert (row["id"], row["project_id"]) == ("BE-1", "p2")
    # Positive control: filtering by Project keeps only that Project's board.
    assert [b["project_id"] for b in work_store.list_work(two.scope, {"project_id": "p1"})["boards"]] == ["p1"]


def test_a_claim_naming_the_second_project_edits_the_second_brain(two):
    """Mutation: look the writer up by bare slot (``_view_board`` ignores ``project_id``) -> the first brain changes."""
    _instance(two.ws)
    before = git("rev-parse", "main", cwd=two.alpha.origin)
    params = {"request_id": "claim-1", "slot": "launcher", "project_id": "p2", "task_id": "BE-1",
              "who": "persona:personainst_a"}
    reply = work_store.claim(two.scope, params, "operator")
    assert reply["task"]["project_id"] == "p2" and reply["task"]["taken"]["who"] == "persona:personainst_a"
    assert reply["receipt"]["ref"]["project_id"] == "p2"
    assert "TAKEN" in git("show", f"main:{NOTE}", cwd=two.beta.origin)
    assert git("rev-parse", "main", cwd=two.alpha.origin) == before


def test_a_run_record_saved_with_a_three_field_ref_still_loads(two):
    """Mutation: make ``RowRef.project_id`` required (drop its default) -> TypeError."""
    raw = {"request_id": "r", "ref": {"slot": "launcher", "note": NOTE, "id": "BE-1"}, "workspace_id": two.ws,
           "persona_instance_id": "pi", "root_session_id": "", "client_message_id": "", "started_at": T0,
           "state": RecordState.RUNNING.value}
    record = RunRecord.from_wire(raw)
    assert record.ref == RowRef("launcher", NOTE, "BE-1") and record.ref.project_id is None
    assert RowRef.of(["launcher", NOTE, "BE-1"]) == record.ref
    assert RowRef.of(["launcher", NOTE, "BE-1", "p2"]).key == "p2/launcher"


def test_a_ref_with_no_project_that_two_projects_answer_refuses_slot_ambiguous(two):
    """Mutation: return the first owner in ``pick`` -> no refusal (the first board is guessed)."""
    with pytest.raises(WorkRefused) as refused:
        work_store.set_status(two.scope, {"request_id": "s-1", "slot": "launcher", "task_id": "BE-1",
                                          "status": "READY 2026-10-31"}, "operator")
    assert refused.value.reason is Reason.SLOT_AMBIGUOUS
    assert "p1/launcher" in refused.value.detail and "p2/launcher" in refused.value.detail
    # Positive control: the same call naming its Project lands.
    reply = work_store.set_status(two.scope, {"request_id": "s-2", "slot": "launcher", "project_id": "p2",
                                              "task_id": "BE-1", "status": "BLOCKED 2026-10-31: upstream — x"},
                                  "operator")
    assert reply["task"]["status_word"] == "BLOCKED"
