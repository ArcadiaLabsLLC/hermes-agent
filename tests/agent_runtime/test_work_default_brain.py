"""The machine-local default brain normalizes into a repo brain (owner ruling 2026-10-18,
``RT-WORK-DEFAULT-BRAIN-REALM``): every workspace with no repo brain gets one; once a repo slot with a
brain is bound, the default board's rows move there in ONE commit with their IDs kept, the default
board drops from the list, and new rows land in the repo brain."""
import json
import subprocess
from pathlib import Path

from agent_runtime import paths
from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.machine_roots import load_machine_roots, write_machine_roots
from agent_runtime.store import WorkspaceStore
from agent_runtime.work import service, store
from agent_runtime.work_store import board
from agent_runtime.work_store.grammar import parse_note
from agent_runtime.workspace_slots import declare
from tests.agent_runtime.persona_instance_mint import mint_free_floating
from tests.agent_runtime.test_work_service import call, start, work  # noqa: F401

BRAIN = "Harness_Brain/20 — Active Initiatives"
MOVED_NOTE = f"{BRAIN}/work-queue.md"
QUEUE = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n- **`RT-A` — repo row** · READY 2026-10-18\n"
ID = ("-c", "user.name=Test Session", "-c", "user.email=session@test.invalid", "-c", "core.quotePath=false")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *ID, *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def repo_with_brain(root: Path) -> tuple[Path, Path]:
    origin, seed, clone = root / "origin.git", root / "seed", root / "clone"
    root.mkdir(parents=True)
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=root)
    git("clone", "-q", str(origin), str(seed), cwd=root)
    (seed / BRAIN).mkdir(parents=True)
    (seed / BRAIN / "q.md").write_text(QUEUE, encoding="utf-8", newline="\n")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    git("clone", "-q", str(origin), str(clone), cwd=root)
    return origin, clone


def bind(ws: str, **clones: Path) -> None:
    declare(ws, [{"name": name, "repo": {"clone_url": f"https://example.invalid/{name}.git", "default_branch": "main"}}
                 for name in clones], issued_at="2026-10-18T13:00:00+00:00", machine="test-machine")
    roots = dict(load_machine_roots(refresh=True).roots)
    roots.update({name: str(path) for name, path in clones.items()})
    write_machine_roots(roots, dry_run=False)


def commits(origin: Path) -> int:
    return int(git("rev-list", "--count", "main", cwd=origin).strip())


def test_every_workspace_without_a_repo_brain_gets_one_automatically(work):
    other = WorkspaceStore().create(name="Other").id
    surface = paths.office_surface_path(other)
    surface.parent.mkdir(parents=True, exist_ok=True)
    surface.write_text("{}", encoding="utf-8")
    caps = service.execute("capabilities", {}, STDIO_OWNER)
    assert caps["default_brain"][other] == {"state": "created"}
    assert caps["default_brain"][work.ws] == {"state": "present"}
    assert [b.slot for b in board.boards(other)] == ["brain"]


def test_binding_a_repo_brain_moves_the_open_rows_once_and_drops_the_default_board(work, tmp_path):
    alice = mint_free_floating("alice")
    first = start(work, "q1", title="First")["task"]["id"]
    second = start(work, "q2", title="Second")["task"]["id"]
    call(work, "claim", request_id="c1", slot="brain", task_id=second, who=f"persona:{alice.id}")
    origin, clone = repo_with_brain(tmp_path / "hermes")
    before = commits(origin)
    bind(work.ws, hermes=clone)
    listed = call(work, "list")
    assert [b["slot"] for b in listed["boards"]] == ["hermes"]
    assert {row["id"]: row["note"] for row in listed["rows"]} == {"RT-A": f"{BRAIN}/q.md", first: MOVED_NOTE,
                                                                  second: MOVED_NOTE}
    assert next(row for row in listed["rows"] if row["id"] == second)["taken"]["who"] == f"persona:{alice.id}"
    assert commits(origin) == before + 1
    moved = parse_note(git("show", f"main:{MOVED_NOTE}", cwd=origin), slot="hermes", note=MOVED_NOTE)
    assert [row.ref.id for row in moved] == [first, second] and not any(row.defects for row in moved)
    default_note = paths.default_brain_dir(work.ws) / "Work_Brain/20 — Active Initiatives/work-queue.md"
    left = git("show", "main:Work_Brain/20 — Active Initiatives/work-queue.md", cwd=default_note.parents[2])
    assert parse_note(left, slot="brain", note="q") == []
    assert json.loads(board.binding_path(work.ws).read_text(encoding="utf-8"))["retired_into"] == "hermes"
    call(work, "list")
    assert commits(origin) == before + 1


def test_new_rows_go_to_the_repo_brain_even_before_the_move(work, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "normalize_default_brain", lambda ws: None)
    _, clone = repo_with_brain(tmp_path / "hermes")
    bind(work.ws, hermes=clone)
    assert [b["slot"] for b in call(work, "list")["boards"]] == ["hermes", "brain"]
    assert start(work, "q1", title="Engine work")["task"]["slot"] == "hermes"


def test_the_first_bound_slot_by_name_receives_the_move(work, tmp_path):
    """Declared zeta-then-alpha; the slot document is keyed by name, so alpha (first by name) receives."""

    start(work, "q1", title="Moves")
    zeta_origin, zeta = repo_with_brain(tmp_path / "zeta")
    alpha_origin, alpha = repo_with_brain(tmp_path / "alpha")
    bind(work.ws, zeta=zeta, alpha=alpha)
    call(work, "list")
    assert commits(alpha_origin) == 2 and commits(zeta_origin) == 1
    assert json.loads(board.binding_path(work.ws).read_text(encoding="utf-8"))["retired_into"] == "alpha"


def test_an_empty_default_brain_retires_without_a_commit(work, tmp_path):
    origin, clone = repo_with_brain(tmp_path / "hermes")
    bind(work.ws, hermes=clone)
    caps = service.execute("capabilities", {}, STDIO_OWNER)
    assert caps["default_brain"][work.ws] == {"state": "moved", "into": "hermes"}
    assert commits(origin) == 1 and board.default_board(work.ws) is None
