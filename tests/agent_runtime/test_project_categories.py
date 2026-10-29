"""A Project's category folders as hermes reads them (plan project-slots-and-shared-chats §7, row RT-PROJECT-CATEGORY-FOLDERS)."""

from __future__ import annotations

from hermes_time import now

from agent_runtime import paths, project_migration, serve_rpc
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_slots import load_slot_context, set_instance_slots
from agent_runtime.project_store import ProjectStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import WorkspaceStore
from agent_runtime.work_store.board import declared_boards
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import bind_project, declare

T0 = "2026-10-29T10:00:00+00:00"
T1 = "2026-10-29T11:00:00+00:00"


def _setup(tmp_path, *names):
    ProjectStore().declare("p1", [{"name": n, "repo": {"clone_url": f"https://example.com/{n}.git"},
                                   "context": {"files": []}} for n in names], issued_at=T0, machine="m", name="Eternia")
    for name in names:
        folder = tmp_path / name
        folder.mkdir()
        bind_project("p1", name, str(folder), issued_at=T0)
    workspace = WorkspaceStore().create(name="Team").id
    set_project_connection(workspace, "p1", connected=True, expected_revision=0)
    PersonaInstanceStore()._write(PersonaInstance(
        id="personainst_a", persona_id="dev", role="dev", display_name="a", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace, updated_at=now()))
    set_instance_slots("personainst_a", [f"p1/{names[0]}"], issued_at=T1)
    return workspace


def _context():
    return load_slot_context(PersonaInstanceStore().get("personainst_a"))


def test_only_the_listed_documents_load_as_sections(tmp_path):
    _setup(tmp_path, "launcher")
    docs = tmp_path / "launcher" / "docs"
    docs.mkdir()
    (docs / "listed.md").write_text("the listed one", encoding="utf-8")
    (docs / "CLAUDE.md").write_text("never offered", encoding="utf-8")
    ProjectStore().set_category("p1", "documents", slot="launcher", subpath="docs", shared=False, issued_at=T0,
                                context_files=["listed.md", "gone.md"])
    context = _context()
    assert [(s.heading, s.content) for s in context.sections] == [("## Eternia/documents — listed.md", "the listed one")]
    statuses = {r["file"]: r.get("included") for r in context.receipts if r.get("kind") == "project_context"}
    assert statuses["listed.md"] is True and statuses["gone.md"] is False
    assert "never offered" not in context.content


def test_guidance_loads_only_while_shared(tmp_path):
    _setup(tmp_path, "launcher")
    store = ProjectStore()
    store.set_category("p1", "guidance", slot=None, subpath=None, shared=True, issued_at=T0)
    store.set_guidance("p1", description="A launcher.", instructions="Prefer tokens.", issued_at=T0)
    assert [(s.heading, s.content) for s in _context().sections] == [("## Eternia — guidance", "A launcher.\n\nPrefer tokens.")]
    store.set_category("p1", "guidance", slot=None, subpath=None, shared=False, issued_at=T1)
    assert _context().sections == ()


def test_a_project_board_is_the_boards_slot_and_a_migrated_document_lists_none_twice(tmp_path):
    workspace = _setup(tmp_path, "launcher", "backend")
    assert [(b.slot, b.project_id) for b in declared_boards(workspace)] == [("backend", "p1"), ("launcher", "p1")]
    ProjectStore().set_category("p1", "boards", slot="launcher", subpath=None, shared=True, issued_at=T0)
    assert [(b.slot, b.project_id, b.checkout) for b in declared_boards(workspace)] == [
        ("launcher", "p1", tmp_path / "launcher")]
    legacy = WorkspaceStore().create(name="Legacy").id
    declare(legacy, [{"name": "brain", "repo": {"local": True}}], issued_at=T0, machine="m")
    assert [(b.slot, b.project_id) for b in declared_boards(legacy)] == [("brain", None)]
    project_migration.migrate_namespace()
    assert [(b.slot, b.project_id) for b in declared_boards(legacy)] == [("brain", f"ws-{legacy}")]


def test_the_artifacts_folder_is_listed_never_written(tmp_path):
    _setup(tmp_path, "launcher")
    out = tmp_path / "launcher" / ".eternia" / "artifacts"
    (out / "deck").mkdir(parents=True)
    (out / "deck" / "slides.pdf").write_bytes(b"x" * 7)
    ProjectStore().set_category("p1", "artifacts", slot="launcher", subpath=None, shared=False, issued_at=T0)
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.project.artifacts.list",
                                      "params": {"project_id": "p1"}})["result"]
    assert reply == {"project_id": "p1", "here": True, "files": [{"name": "deck/slides.pdf", "size": 7}],
                     "truncated": False}
