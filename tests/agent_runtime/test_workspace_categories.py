"""A workspace's category folders as hermes reads them: its documents and guidance offered to its agents, and
its default board (launcher plan ``WORKSPACE_ABSORBS_PROJECTS_2026-11-04.md`` §3, row RT-WS-ABSORB-RETIRE-PROJECT)."""

from __future__ import annotations

from hermes_time import now

from agent_runtime import paths
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_slots import CategoryContext, load_category_context, set_instance_slots
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import WorkspaceStore
from agent_runtime.work_store.board import declared_boards, preferred
from agent_runtime.workspace_categories import set_category, set_guidance
from agent_runtime.workspace_slots import bind, declare

T0 = "2026-10-29T10:00:00+00:00"
T1 = "2026-10-29T11:00:00+00:00"


def _setup(tmp_path, *names):
    workspace = WorkspaceStore().create(name="Eternia").id
    declare(workspace, [{"name": n, "repo": {"clone_url": f"https://example.com/{n}.git"}, "context": {"files": []}}
                        for n in names], issued_at=T0, machine="m")
    for name in names:
        folder = tmp_path / name
        folder.mkdir()
        bind(workspace, name, str(folder), issued_at=T0)
    PersonaInstanceStore()._write(PersonaInstance(
        id="personainst_a", persona_id="dev", role="dev", display_name="a", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace, updated_at=now()))
    set_instance_slots("personainst_a", [names[0]], issued_at=T1)
    return workspace


def _context():
    return load_category_context(PersonaInstanceStore().get("personainst_a")) or CategoryContext()


def test_only_the_listed_documents_load_as_sections(tmp_path):
    workspace = _setup(tmp_path, "launcher")
    docs = tmp_path / "launcher" / "docs"
    docs.mkdir()
    (docs / "listed.md").write_text("the listed one", encoding="utf-8")
    (docs / "CLAUDE.md").write_text("never offered", encoding="utf-8")
    set_category(workspace, "documents", slot="launcher", subpath="docs", shared=False, issued_at=T0,
                 context_files=["listed.md", "gone.md"])
    context = _context()
    assert [(s.heading, s.content) for s in context.sections] == [("## Eternia/documents — listed.md", "the listed one")]
    statuses = {r["file"]: r.get("included") for r in context.receipts if r.get("kind") == "workspace_category"}
    assert statuses["listed.md"] is True and statuses["gone.md"] is False
    assert "never offered" not in context.content


def test_guidance_loads_only_while_shared(tmp_path):
    workspace = _setup(tmp_path, "launcher")
    set_category(workspace, "guidance", slot=None, subpath=None, shared=True, issued_at=T0)
    set_guidance(workspace, description="A launcher.", instructions="Prefer tokens.", issued_at=T0)
    assert [(s.heading, s.content) for s in _context().sections] == [("## Eternia — guidance", "A launcher.\n\nPrefer tokens.")]
    set_category(workspace, "guidance", slot=None, subpath=None, shared=False, issued_at=T1)
    assert _context().sections == ()


def test_every_slot_is_a_board_the_boards_slot_is_its_default(tmp_path):
    """The boards category names the workspace's one default board, listed first; never a filter.

    Mutation: compare ``name == default`` against a constant ``False`` in ``declared_boards`` -> no board is
    the default and ``preferred`` keeps name order, red."""
    workspace = _setup(tmp_path, "launcher", "backend")
    assert [(b.slot, b.board_default) for b in declared_boards(workspace)] == [("backend", False), ("launcher", False)]
    set_category(workspace, "boards", slot="launcher", subpath=None, shared=True, issued_at=T0)
    found = declared_boards(workspace)
    assert [(b.slot, b.checkout, b.board_default) for b in found] == [
        ("backend", tmp_path / "backend", False), ("launcher", tmp_path / "launcher", True)]
    assert [b.slot for b in preferred(found)] == ["launcher", "backend"]


def test_an_unassigned_instance_gets_the_workspaces_guidance_and_keeps_its_agents_file(tmp_path):
    """The category block is its own turn field, not the slot context.

    Positive control: the same instance, assigned, carries the same block after its slot sections.
    """
    from agent_runtime.mission_chat_turn_context import DEFAULT_RESOLVERS, _turn_workspace, workspace_content

    workspace = _setup(tmp_path, "launcher")
    set_category(workspace, "guidance", slot=None, subpath=None, shared=True, issued_at=T0)
    set_guidance(workspace, description="A launcher.", instructions="Prefer tokens.", issued_at=T0)
    agents = tmp_path / "AGENTS.md"
    agents.write_text("the alias file", encoding="utf-8")
    set_instance_slots("personainst_a", [], issued_at="2026-10-29T12:00:00+00:00")
    instance = PersonaInstanceStore().get("personainst_a")
    slot_context, alias, receipt, _workdir, categories = _turn_workspace(DEFAULT_RESOLVERS, None, instance, str(agents))
    assert slot_context is None and alias.content.strip() == "the alias file"  # the alias is not superseded
    content = workspace_content(slot_context, alias, categories)
    assert "the alias file" in content and "## Eternia — guidance\n\nA launcher.\n\nPrefer tokens." in content
    assert [r["label"] for r in receipt["categories"]] == ["Eternia/guidance"]
    set_instance_slots("personainst_a", ["launcher"], issued_at="2026-10-29T13:00:00+00:00")
    assigned = _turn_workspace(DEFAULT_RESOLVERS, None, PersonaInstanceStore().get("personainst_a"), None)
    assert assigned[0] is not None and "## Eternia — guidance" in workspace_content(assigned[0], None, assigned[4])
