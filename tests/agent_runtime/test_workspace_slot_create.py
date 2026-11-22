"""A phone keeps its project folders in its own namespace (Eternia row
``MC-PHONE-FILES-A-PHONE-KEEPS-PROJECT-FOLDERS-IN-ITS-NAMESPACE``, plan
``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §3, owner ruling 2026-11-21).

A project on a phone is an ordinary folder in Eternia's own storage, bound as a slot so the agents and the
engine see it. A phone starts no process, so:

* **Create** (``runtime.workspace.slot.create``) makes a LOCAL slot's folder in the Harness's own folder,
  a git repository through the realm-sync port, and binds it; the caller names no path.
* **Clone** runs in process through the port (``realm_sync.git_backend: dulwich``), on its own thread,
  and binds on success, with the same run row a spawned clone has.
* **The probe** reads a bound checkout's ``origin`` through the port, never by spawning ``git``.

Killing mutations are named per test and in the code they kill.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from agent_runtime import serve_rpc, workspace_slot_setup
from agent_runtime.call_authorization import LOCAL_CONSOLE_METHODS
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.project_files.agent_tree import _admissible
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slot_clone_home import repos_root
from agent_runtime.workspace_slot_runs import all_runs
from agent_runtime.workspace_slot_setup import clone_slot, settle_runs
from agent_runtime.workspace_slots import load_document, write_document

ISSUED = "2026-11-21T12:00:00+00:00"
LATER = "2026-11-21T13:00:00+00:00"
APP_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"


def call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _workspace(slots: list[dict]) -> str:
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name="Phone").id
    reply = call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": slots, "issued_at": ISSUED})
    assert "result" in reply, reply
    return workspace_id


def _local(name: str) -> dict:
    return {"name": name, "repo": {"clone_url": None, "default_branch": "main", "local": True}}


def _remote(name: str, url: str = APP_URL) -> dict:
    return {"name": name, "repo": {"clone_url": url, "default_branch": "main"}}


@pytest.fixture
def phone(monkeypatch):
    """A device that starts no process: the pure-Python git, and a ``git`` program that cannot run."""

    import agent_runtime.realm_sync.git  # noqa: F401 -- imported BEFORE the stand-in is placed: a module
    import agent_runtime.realm_sync.git_binary  # noqa: F401 -- first imported under it keeps it after the test
    from tests.agent_runtime.conftest import _use_realm_sync_backend

    _use_realm_sync_backend(monkeypatch, "dulwich")

    def no_git(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    from agent_runtime import workspace_slots_probe

    monkeypatch.setattr(workspace_slots_probe, "_run", no_git)


def _origin(tmp_path: Path) -> Path:
    """A repository with one commit to clone from, made by the git program before the phone starts."""

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
    (source / "README.md").write_text("hello from the phone\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "-m", "one"], check=True)
    return source


def _declare_url(workspace_id: str, slot: str, url: str) -> None:
    """A local path is no declarable clone URL; the document is written as a synced one would land."""

    document = load_document(workspace_id)
    document["slots"][slot]["repo"]["clone_url"] = url
    write_document(workspace_id, document)


# ── Create ───────────────────────────────────────────────────────────────────


def test_create_makes_a_git_folder_in_the_namespace_and_binds_it(phone):
    """Killing mutation: drop ``_port(dest).init()`` in ``create_slot`` -> no ``.git``, the probe answers
    ``folder`` and this test is red."""

    workspace = _workspace([_local("notes")])
    assert "runtime.workspace.slot.create" in LOCAL_CONSOLE_METHODS
    reply = call("runtime.workspace.slot.create", {"workspace_id": workspace, "slot": "notes", "issued_at": ISSUED})
    bound = reply["result"]
    folder = Path(bound["path"])
    assert bound["bound_here"] is True and folder.is_dir() and (folder / ".git").is_dir()
    assert folder.parent.parent == repos_root() and folder.name == "notes"
    assert bound["report"]["checkout"] == "local" and bound["report"]["status"] == "ready"
    # It is an agent root: a folder inside the namespace, never the namespace itself.
    assert _admissible(str(folder))
    here = call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]["notes"]
    assert here["bound_here"] is True and here["path"] == str(folder)


def test_create_takes_no_path_from_the_caller(phone, tmp_path):
    workspace = _workspace([_local("notes")])
    elsewhere = tmp_path / "elsewhere"
    bound = call("runtime.workspace.slot.create", {"workspace_id": workspace, "slot": "notes", "issued_at": ISSUED,
                                                   "path": str(elsewhere), "dest_path": str(elsewhere)})["result"]
    assert not elsewhere.exists() and Path(bound["path"]).parent.parent == repos_root()


def test_a_second_project_of_one_name_gets_its_own_folder(phone):
    """Killing mutation: drop the "holds anything" arm of ``default_project_path`` -> the second project is
    made inside the first one's files, red."""

    first = _workspace([_local("notes")])
    taken = Path(call("runtime.workspace.slot.create", {"workspace_id": first, "slot": "notes",
                                                        "issued_at": ISSUED})["result"]["path"])
    (taken / "kept.md").write_text("mine\n", encoding="utf-8")
    call("runtime.workspace.slot.unbind", {"workspace_id": first, "slot": "notes"})  # free by binding, not by disk
    again = Path(call("runtime.workspace.slot.create", {"workspace_id": first, "slot": "notes",
                                                        "issued_at": LATER})["result"]["path"])
    assert again != taken and again.name == "notes-2" and (taken / "kept.md").read_text(encoding="utf-8") == "mine\n"


def test_create_refuses_a_slot_with_a_repository_and_one_already_bound(phone):
    workspace = _workspace([_local("notes"), _remote("app")])
    refused = call("runtime.workspace.slot.create", {"workspace_id": workspace, "slot": "app", "issued_at": ISSUED})
    assert refused["error"]["data"]["reason"] == "slot_has_repository"
    assert "result" in call("runtime.workspace.slot.create", {"workspace_id": workspace, "slot": "notes",
                                                              "issued_at": ISSUED})
    again = call("runtime.workspace.slot.create", {"workspace_id": workspace, "slot": "notes", "issued_at": LATER})
    assert again["error"]["data"]["reason"] == "slot_already_bound"


# ── Clone, in process ────────────────────────────────────────────────────────


def test_a_device_without_processes_clones_in_process_and_binds(phone, tmp_path):
    """Killing mutation: drop the in-process arm of ``clone_slot`` -> it reaches the process registry
    (``tools.process_registry``, not packaged on a phone) and this test is red."""

    source = _origin(tmp_path)
    workspace = _workspace([_remote("app")])
    _declare_url(workspace, "app", str(source))
    dest = repos_root() / "local" / "app"
    reply = clone_slot(workspace, "app", str(dest), issued_at=ISSUED, watch=False)
    run = reply["run"]
    assert run["in_process"] is True and run["work_id"] is None
    assert run["status"] == "succeeded", run
    assert (dest / "README.md").read_text(encoding="utf-8") == "hello from the phone\n"
    here = call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]["app"]
    assert here["bound_here"] is True and here["path"] == str(dest)


def test_the_serve_verb_clones_on_a_thread_and_the_run_settles(phone, tmp_path):
    source = _origin(tmp_path)
    workspace = _workspace([_remote("app")])
    _declare_url(workspace, "app", str(source))
    dest = repos_root() / "local" / "app"
    reply = call("runtime.workspace.slot.clone", {"workspace_id": workspace, "slot": "app", "dest_path": str(dest),
                                                  "issued_at": ISSUED})["result"]
    run_id = reply["run"]["run_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = next(r for r in all_runs() if r["run_id"] == run_id)
        if run["status"] != "running":
            break
        time.sleep(0.05)
    assert run["status"] == "succeeded", run
    assert (dest / ".git").is_dir()


def test_a_failed_in_process_clone_ends_with_a_typed_reason(phone, tmp_path):
    workspace = _workspace([_remote("app")])
    _declare_url(workspace, "app", str(tmp_path / "no-such-repository"))
    run = clone_slot(workspace, "app", str(repos_root() / "local" / "app"), issued_at=ISSUED, watch=False)["run"]
    assert run["status"] == "failed" and run["reason"] == "clone_repository_not_found", run
    assert call("runtime.workspace.slots.show", {"workspace_id": workspace})["result"]["here"]["app"]["bound_here"] is False


def test_a_running_in_process_clone_is_not_settled_as_lost(phone, tmp_path, monkeypatch):
    """Killing mutation: settle an in-process run through the process registry -> a live clone reads
    ``lost`` the moment Set up is read, red."""

    workspace = _workspace([_remote("app")])
    monkeypatch.setattr(workspace_slot_setup.threading, "Thread",
                        lambda **kwargs: type("Held", (), {"start": lambda self: None})())
    run = clone_slot(workspace, "app", str(repos_root() / "local" / "app"), issued_at=ISSUED)["run"]
    assert run["status"] == "running"
    settled = {r["run_id"]: r for r in settle_runs(workspace, registry=object())}
    assert settled[run["run_id"]]["status"] == "running"
    # A serve that restarted no longer runs it: then it is lost.
    workspace_slot_setup._IN_PROCESS_RUNS.discard(run["run_id"])
    settled = {r["run_id"]: r for r in settle_runs(workspace, registry=object())}
    assert settled[run["run_id"]]["status"] == "lost"


# ── the probe ────────────────────────────────────────────────────────────────


def test_a_phone_probes_its_clone_without_a_git_program(phone, tmp_path):
    """Killing mutation: read ``origin`` by spawning ``git remote get-url`` again -> the phone's probe
    answers ``unknown`` and this test is red."""

    source = _origin(tmp_path)
    workspace = _workspace([_remote("app", url=APP_URL)])
    _declare_url(workspace, "app", str(source))
    dest = repos_root() / "local" / "app"
    clone_slot(workspace, "app", str(dest), issued_at=ISSUED, watch=False)
    row = call("runtime.workspace.slots.report", {"workspace_id": workspace})["result"]["slots"]["app"]
    assert row["checkout"] == "matches" and row["status"] == "ready", row
    assert not row["unknowns"]
