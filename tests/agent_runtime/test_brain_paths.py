"""RT-BRAIN-PATHS-PLAIN-LIST: the brain-path list hermes writes and Eternia reads (the w1102c contract).

The contract test builds the fixture's namespace — two workspaces (Alpha with its own brain and a Project
holding a bound slot with a brain, an unbound slot and a bound slot with no brain; Beta with nothing), and a
personal brain — and asserts the writer's output equals ``tests/fixtures/brain_paths_v1.json`` once each
real path is named by its placeholder. The rest pin the chokepoints: each write rewrites the file.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_runtime import brain_paths
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.project_store import ProjectStore
from agent_runtime.store import WorkspaceStore
from agent_runtime.work_store.board import PERSONAL_BOARD_ID
from agent_runtime.work_store.default_brain import ensure_default_brain
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import bind_project

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "brain_paths_v1.json"
T0 = "2026-11-02T22:00:00+00:00"
WRITTEN = datetime(2026, 11, 2, 23, 0, tzinfo=UTC)


def _checkout(root: Path, brain: str | None) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    if brain:
        queue = root / brain / "20 — Active Initiatives"
        queue.mkdir(parents=True)
        (queue / "q.md").write_text("---\ntype: queue\n---\n", encoding="utf-8")
    return root


def _slot(name: str) -> dict:
    return {"name": name, "repo": {"clone_url": f"https://example.com/{name}.git", "default_branch": "main"}}


@pytest.fixture
def namespace(tmp_path: Path) -> dict[str, str]:
    """The fixture's namespace; answers ``{real path: placeholder}``."""

    machine_roots_cache_clear()
    WorkspaceStore().create(name="Alpha", workspace_id="ws-alpha")
    WorkspaceStore().create(name="Beta", workspace_id="ws-beta")
    personal = ensure_default_brain(PERSONAL_BOARD_ID, issued_at=T0)
    # Alpha's own brain is made while it holds no Project brain: today's work store retires a default brain
    # into the first bound repo brain (``work/store.py::normalize_default_brain``), so it is never made after.
    alpha = ensure_default_brain("ws-alpha", issued_at=T0)
    ProjectStore().declare("proj-app", [_slot("launcher"), _slot("backend"), _slot("hermes")],
                           issued_at=T0, machine="m", name="App")
    launcher = _checkout(tmp_path / "src" / "launcher", "Launcher_Brain")
    hermes = _checkout(tmp_path / "src" / "hermes", None)
    bind_project("proj-app", "launcher", str(launcher), issued_at=T0)
    bind_project("proj-app", "hermes", str(hermes), issued_at=T0)
    set_project_connection("ws-alpha", "proj-app", connected=True, expected_revision=0)
    return {str(personal.checkout): "/home/user/.hermes/hermes-namespaces/ns/personal-brain",
            str(alpha.checkout): "/home/user/.hermes/hermes-namespaces/ns/workspace-brains/ws-alpha",
            str(launcher): "/home/user/src/launcher", str(hermes): "/home/user/src/hermes"}


def _placeholders(node, names: dict[str, str]):
    if isinstance(node, dict):
        return {key: (names.get(value, value) if key == "path" and isinstance(value, str) else _placeholders(value, names))
                for key, value in node.items()}
    if isinstance(node, list):
        return [_placeholders(item, names) for item in node]
    return node


@pytest.mark.parametrize("owner", [PERSONAL_BOARD_ID, "ws-local"])
def test_local_writer_publishes_accepted_rows_for_file_only_readers(owner):
    """Mutation: publish board.checkout again -> accepted row disappears after reopen."""
    from agent_runtime.work_store.grammar import Op, RowRef
    from agent_runtime.work_store.writer import RowOp, Writer

    if owner != PERSONAL_BOARD_ID:
        WorkspaceStore().create(name="Local", workspace_id=owner)
    board = ensure_default_brain(owner, issued_at=T0)
    note = f"{board.brain_dir}/work-queue.md"
    row = "- **`WORK-A2B3C4` — Saved task** · READY 2026-11-03"
    writer = Writer(board, machine_id="test")
    writer.apply(RowOp(RowRef(board.slot, note, "WORK-A2B3C4"), Op.APPEND,
                       "operator", "saved-row", {"row": row}))

    def entry(payload):
        return payload["personal"] if owner == PERSONAL_BOARD_ID else payload["workspaces"][owner]["brain"]

    # The creation chokepoint updates current readers; boot rebuilding uses the
    # same existing worktree without creating or resetting anything.
    current = entry(brain_paths.read_brain_paths())
    reopened = entry(brain_paths.build_brain_paths())
    assert current["path"] == reopened["path"] == str(writer.worktree)
    assert row in (Path(current["path"]) / note).read_text(encoding="utf-8")
    assert row not in (board.checkout / note).read_text(encoding="utf-8")


def test_the_writer_output_for_the_fixture_namespace_is_the_fixture(namespace):
    """Mutations: report the queue dir instead of the brain folder -> brain_dir red; drop the ``archived``
    skip / the ``path is_dir`` gate -> red; ``behind`` keyed wrong -> red."""
    real = {path: count for path, count in ((p, {"/home/user/.hermes/hermes-namespaces/ns/workspace-brains/ws-alpha": 0,
                                                 "/home/user/src/launcher": 2}.get(name)) for p, name in namespace.items())
            if count is not None}
    built = brain_paths.build_brain_paths(behind=real, now=WRITTEN)
    assert _placeholders(built, namespace) == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_written_file_is_the_build_and_an_unchanged_list_is_not_rewritten(namespace):
    assert brain_paths.write_brain_paths(now=WRITTEN) in (True, False)
    held = json.loads(brain_paths.brain_paths_path().read_text(encoding="utf-8"))
    assert held["schema_version"] == brain_paths.BRAIN_PATHS_SCHEMA_VERSION
    assert set(held["workspaces"]) == {"ws-alpha", "ws-beta"}
    assert brain_paths.write_brain_paths(now=datetime(2027, 1, 1, tzinfo=UTC)) is False
    assert json.loads(brain_paths.brain_paths_path().read_text(encoding="utf-8"))["written_at"] == held["written_at"]


def test_an_archived_workspace_is_left_out(namespace):
    """Mutation: list ``include_archived=True`` in ``build_brain_paths`` -> red."""
    WorkspaceStore().archive("ws-beta")
    assert set(json.loads(brain_paths.brain_paths_path().read_text(encoding="utf-8"))["workspaces"]) == {"ws-alpha"}


def test_a_held_behind_count_survives_a_rewrite_that_does_not_measure(namespace):
    launcher = next(path for path, name in namespace.items() if name == "/home/user/src/launcher")
    brain_paths.write_brain_paths(behind={launcher: 3})
    WorkspaceStore().rename("ws-beta", "Beta two")
    held = json.loads(brain_paths.brain_paths_path().read_text(encoding="utf-8"))
    slot = next(s for s in held["workspaces"]["ws-alpha"]["projects"][0]["slots"] if s["slot"] == "launcher")
    assert held["workspaces"]["ws-beta"]["name"] == "Beta two" and slot["behind"] == 3


def _listed() -> dict:
    return json.loads(brain_paths.brain_paths_path().read_text(encoding="utf-8"))


# ── one test per chokepoint: the write changes the file ─────────────────────


def test_creating_a_workspace_rewrites_the_list():
    """Mutation: drop ``_brain_paths_changed`` from ``WorkspaceStore.create`` -> red."""
    WorkspaceStore().create(name="Gamma", workspace_id="ws-gamma")
    assert "ws-gamma" in _listed()["workspaces"]


def test_saving_a_workspace_rewrites_the_list():
    """Mutation: drop it from ``WorkspaceStore._save_unlocked`` -> red."""
    WorkspaceStore().create(name="Gamma", workspace_id="ws-gamma")
    WorkspaceStore().rename("ws-gamma", "Gamma two")
    assert _listed()["workspaces"]["ws-gamma"]["name"] == "Gamma two"


def test_deleting_a_workspace_rewrites_the_list():
    """Mutation: drop it from ``WorkspaceStore.delete`` -> red."""
    WorkspaceStore().create(name="Gamma", workspace_id="ws-gamma")
    WorkspaceStore().delete("ws-gamma")
    assert "ws-gamma" not in _listed()["workspaces"]


def test_writing_a_project_rewrites_the_list(namespace):
    """Mutation: drop ``changed`` from ``project_store.write_project`` -> red."""
    ProjectStore().declare("proj-app", [_slot("launcher"), _slot("hermes")], issued_at="2026-11-02T22:30:00+00:00",
                           machine="m", name="App renamed")
    project = _listed()["workspaces"]["ws-alpha"]["projects"][0]
    assert project["name"] == "App renamed" and [s["slot"] for s in project["slots"]] == ["hermes", "launcher"]


def test_binding_a_slot_rewrites_the_list(namespace, tmp_path, monkeypatch):
    """Mutation: drop ``changed`` from ``workspace_slots._write_fill`` -> red (the bind's machine report, which
    also writes the Project record, is stubbed so only the fill's own call can rewrite the list)."""
    from agent_runtime import workspace_slots_probe

    monkeypatch.setattr(workspace_slots_probe, "report_project", lambda *_a, **_k: {"slots": {}})
    backend = _checkout(tmp_path / "src" / "backend", "EterniaBackend_Brain")
    bind_project("proj-app", "backend", str(backend), issued_at=T0)
    slot = next(s for s in _listed()["workspaces"]["ws-alpha"]["projects"][0]["slots"] if s["slot"] == "backend")
    assert slot == {"slot": "backend", "path": str(backend), "brain_dir": "EterniaBackend_Brain", "behind": None}


def test_a_default_brain_binding_rewrites_the_list():
    """Mutation: drop ``changed`` from ``default_brain._write_binding`` -> red."""
    WorkspaceStore().create(name="Gamma", workspace_id="ws-gamma")
    made = ensure_default_brain("ws-gamma", issued_at=T0)
    assert _listed()["workspaces"]["ws-gamma"]["brain"] == {"path": str(made.checkout), "brain_dir": "Work_Brain",
                                                            "behind": None}


def test_a_slot_document_write_rewrites_the_list(monkeypatch):
    """Mutation: drop ``changed`` from ``workspace_slots.write_document`` -> red."""
    from agent_runtime import workspace_slots

    seen: list[str] = []
    monkeypatch.setattr(brain_paths, "write_brain_paths", lambda **_: seen.append("w") or True)
    workspace_slots.write_document("ws-x", workspace_slots.empty_document("ws-x"))
    assert seen == ["w"]


def test_copying_path_fills_in_the_project_migration_rewrites_the_list(monkeypatch, tmp_path):
    """Mutation: drop ``changed`` from ``project_migration._copy_path_fills`` -> red."""
    from agent_runtime import project_migration
    from agent_runtime.machine_roots import load_machine_roots, write_machine_roots

    current = load_machine_roots(refresh=True)
    write_machine_roots(dict(current.roots), workspace_roots={"ws-x": {"s": str(tmp_path)}}, dry_run=False)
    seen: list[str] = []
    monkeypatch.setattr(brain_paths, "write_brain_paths", lambda **_: seen.append("w") or True)
    project_migration._copy_path_fills("ws-x", "ws-ws-x")
    assert seen == ["w"]


def test_the_list_is_written_once_at_serve_boot_before_the_heavy_steps(monkeypatch):
    """Mutation: drop the call in ``BootPhases._boot_store_and_identity`` -> red."""
    from hermes_cli.harness_parts.serve.boot_phases import BootPhases

    seen: list[str] = []
    monkeypatch.setattr(brain_paths, "changed", lambda reason: seen.append(reason) or True)
    phases = BootPhases()
    phases.timeline = type("T", (), {"mark": lambda self, name: seen.append(name)})()
    phases.shell = None
    phases._boot_store_and_identity()  # every later step is best effort; a missing shell refuses its own block
    assert seen[:2] == ["store_root_ms", "serve.boot"]


def test_a_reentrant_change_is_dropped(monkeypatch):
    calls: list[str] = []

    def write(**_):
        calls.append("w")
        brain_paths.changed("inner")
        return True

    monkeypatch.setattr(brain_paths, "write_brain_paths", write)
    assert brain_paths.changed("outer") is True and calls == ["w"]


def test_a_failed_rewrite_never_raises_into_its_chokepoint(monkeypatch):
    monkeypatch.setattr(brain_paths, "write_brain_paths", lambda **_: 1 / 0)
    assert brain_paths.changed("x") is False


def test_creating_a_slot_brain_rewrites_the_list(monkeypatch):
    """Mutation: drop ``changed`` from ``work/store.py::create_brain``'s slot arm -> red."""
    from types import SimpleNamespace

    from agent_runtime.work import store as work_store

    board = SimpleNamespace(bound_here=True, brain_dir=None, slot="s", project_id=None)
    writer = SimpleNamespace(apply=lambda _op: SimpleNamespace(wire=dict))
    monkeypatch.setattr(work_store.boards_store, "boards", lambda _ws: [board])
    monkeypatch.setattr(work_store.boards_store, "pick", lambda found, *_: found[0])
    monkeypatch.setattr(work_store, "worktree_brain", lambda found: found)
    monkeypatch.setattr(work_store, "replace", lambda found, **_: found)
    monkeypatch.setattr(work_store, "writer_for", lambda _board: writer)
    monkeypatch.setattr(work_store, "board_wire", lambda *_: {})
    seen: list[str] = []
    monkeypatch.setattr(brain_paths, "write_brain_paths", lambda **_: seen.append("w") or True)
    work_store.create_brain(SimpleNamespace(workspace_id="ws-x"), {"slot": "s", "request_id": "r"}, "operator")
    assert seen == ["w"]


def test_a_realm_pull_that_changed_the_store_rewrites_the_list(tmp_path):
    """Mutation: drop ``changed`` from ``realm_sync.pull.pull_realm_sync`` -> red."""
    from agent_runtime import paths
    from agent_runtime.realm_sync.pull import pull_realm_sync
    from agent_runtime.store import RealmStore

    realm = RealmStore().create(name="Pull Realm")
    repo = tmp_path / "realm-sync-repo"
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q", "realm-sync-repo"], check=True)
    realm.sync_manifest_ref = str(repo)
    RealmStore().save(realm)
    WorkspaceStore().create(name="Pulled", workspace_id="ws-pulled")
    record = paths.workspace_path("ws-pulled")
    synced = repo / "realms" / realm.id / "store" / "workspaces" / record.name
    synced.parent.mkdir(parents=True)
    synced.write_bytes(record.read_bytes())
    record.unlink()  # gone locally behind the store's back: only the pull brings it back
    brain_paths.write_brain_paths()
    assert "ws-pulled" not in _listed()["workspaces"]
    assert pull_realm_sync(realm.id)["state"] == "pulled"
    assert "ws-pulled" in _listed()["workspaces"]


def test_a_declared_brain_dir_wins_over_detection(tmp_path):
    """Slice 2: the work store's one rule (``board.brain_dir_of``). Mutation: hand it ``{}`` instead of the
    declaration in ``brain_paths._project`` -> detection picks ``Alpha_Brain``, red."""
    WorkspaceStore().create(name="Delta", workspace_id="ws-delta")
    root = _checkout(tmp_path / "two", "Alpha_Brain")
    (root / "Zed_Brain" / "20 — Active Initiatives").mkdir(parents=True)
    pinned = {**_slot("two"), "context": {"brain_dir": "Zed_Brain/20 — Active Initiatives"}}
    ProjectStore().declare("proj-two", [pinned, _slot("plain")], issued_at=T0, machine="m", name="Two")
    bind_project("proj-two", "two", str(root), issued_at=T0)
    bind_project("proj-two", "plain", str(root), issued_at=T0)
    set_project_connection("ws-delta", "proj-two", connected=True, expected_revision=0)
    slots = {s["slot"]: s["brain_dir"] for s in _listed()["workspaces"]["ws-delta"]["projects"][0]["slots"]}
    assert slots == {"plain": "Alpha_Brain", "two": "Zed_Brain"}
