"""An agent's own per-slot pick of which context files load (RT-SLOT-CONTEXT-FILE-PICKS).

Per assigned slot an instance may switch ``CLAUDE.md`` / ``AGENTS.md`` on or off and add one
custom ``.md``. The override rides ``runtime.persona.instance.slots.set`` as ``context_files``,
comes back on each ``slots.show`` row, and the slot loader honours it ahead of the declaration's
``context.files`` and the one-file default; its receipts name the override as the reason. No
override keeps today's ruling.
"""

from __future__ import annotations

import types

from hermes_time import now

from agent_runtime import paths, serve_rpc
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_slots import load_slot_context
from agent_runtime.states import WorkerSessionState

T1 = "2026-11-01T13:00:00+00:00"
T2 = "2026-11-01T14:00:00+00:00"
POINTER_AGENTS = "# Canonical Context\n\n[`CLAUDE.md`](CLAUDE.md) is the single canonical agent-context file."


def _workspace(tmp_path, files_by_slot, *, context_files=None):
    from agent_runtime.machine_roots import machine_roots_cache_clear, write_machine_roots
    from agent_runtime.store import WorkspaceStore
    from agent_runtime.workspace_slots import declare

    machine_roots_cache_clear()
    workspace = WorkspaceStore().create(name="Full stack").id
    roots = {}
    for slot, files in files_by_slot.items():
        checkout = tmp_path / "checkouts" / slot
        checkout.mkdir(parents=True)
        for name, body in files.items():
            (checkout / name).write_text(body, encoding="utf-8")
        roots[slot] = str(checkout)
    write_machine_roots(roots, dry_run=False)
    context = {"context": {"files": context_files}} if context_files is not None else {}
    declare(workspace, [{"name": slot, "repo": {"clone_url": f"https://x/{slot}.git"}, **context}
                        for slot in files_by_slot], issued_at="2026-10-04T12:00:00+00:00", machine="mach_test")
    return workspace


def _instance(workspace: str, instance_id: str = "personainst_picks") -> str:
    PersonaInstanceStore()._write(PersonaInstance(
        id=instance_id, persona_id="dev", role="dev", display_name=instance_id, profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace, updated_at=now(),
    ))
    return instance_id


def _call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _set(instance_id, slots, *, context_files=None, issued_at=T1):
    params = {"persona_instance_id": instance_id, "slots": slots, "issued_at": issued_at}
    if context_files is not None:
        params["context_files"] = context_files
    return _call("runtime.persona.instance.slots.set", params)


def _loaded(instance_id):
    return load_slot_context(PersonaInstanceStore().get(instance_id))


def test_no_override_keeps_the_one_file_default_and_shows_null(tmp_path):
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "claude rules", "AGENTS.md": POINTER_AGENTS}})
    agent = _instance(workspace)
    shown = _set(agent, ["launcher"])["result"]
    assert shown["slots"][0]["context_files"] is None
    context = _loaded(agent)
    assert context.content == "## launcher — CLAUDE.md\n\nclaude rules"
    assert all("override_choice" not in item for item in context.receipts)


def test_both_toggles_on_outrank_the_one_file_default(tmp_path):
    """Mutation: drop the ``override is not None`` branch in ``load_slot_context`` -> red (the default loads one)."""
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "claude rules", "AGENTS.md": POINTER_AGENTS}})
    agent = _instance(workspace)
    shown = _set(agent, ["launcher"], context_files={"launcher": {"files": ["AGENTS.md", "CLAUDE.md"]}})["result"]
    assert shown["slots"][0]["context_files"] == {"files": ["CLAUDE.md", "AGENTS.md"], "custom_path": None}
    context = _loaded(agent)
    assert [s.file for s in context.sections] == ["CLAUDE.md", "AGENTS.md"]
    assert {item["label"]: item["override_choice"] for item in context.receipts} == {
        "launcher/CLAUDE.md": "slot_override", "launcher/AGENTS.md": "slot_override"}


def test_a_toggled_off_file_outranks_the_declarations_list_and_says_why(tmp_path):
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "claude rules", "AGENTS.md": "agent rules"}},
                           context_files=["CLAUDE.md", "AGENTS.md"])
    agent = _instance(workspace)
    _set(agent, ["launcher"], context_files={"launcher": {"files": ["AGENTS.md"]}})
    context = _loaded(agent)
    assert context.content == "## launcher — AGENTS.md\n\nagent rules"
    off = next(item for item in context.receipts if item["label"] == "launcher/CLAUDE.md")
    assert (off["included"], off["status"], off["evidence"]) == (False, "override_off", "slot_override")


def test_a_custom_md_loads_as_its_own_section_with_its_path_on_the_receipt(tmp_path):
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "claude rules"}})
    custom = tmp_path / "notes" / "frontend-only.md"
    custom.parent.mkdir()
    custom.write_text("frontend rules", encoding="utf-8")
    agent = _instance(workspace)
    shown = _set(agent, ["launcher"],
                 context_files={"launcher": {"files": [], "custom_path": str(custom)}})["result"]
    assert shown["slots"][0]["context_files"] == {"files": [], "custom_path": str(custom)}
    context = _loaded(agent)
    assert context.content == "## launcher — frontend-only.md\n\nfrontend rules"
    receipt = next(item for item in context.receipts if item["file"] == "frontend-only.md")
    assert (receipt["included"], receipt["custom_path"], receipt["override_choice"]) == (
        True, str(custom), "slot_override")


def test_a_bad_pick_is_refused_and_writes_nothing(tmp_path):
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "c"}, "backend": {"CLAUDE.md": "b"}})
    agent = _instance(workspace)
    for pick in ({"launcher": {"files": ["README.md"]}},
                 {"backend": {"files": []}},
                 {"launcher": {"files": [], "custom_path": "relative/notes.md"}},
                 {"launcher": {"files": [], "custom_path": str(tmp_path / "notes.txt")}},
                 ["launcher"]):
        assert _set(agent, ["launcher"], context_files=pick)["error"]["data"]["reason"] == "context_files_invalid"
    row = PersonaInstanceStore().get(agent)
    assert (row.assigned_slots, row.slot_context_files) == ([], {})


def test_an_omitted_map_keeps_the_override_and_an_unassigned_slot_drops_it(tmp_path):
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "c"}, "backend": {"CLAUDE.md": "b"}})
    agent = _instance(workspace)
    _set(agent, ["launcher", "backend"], context_files={"launcher": {"files": ["AGENTS.md"]},
                                                        "backend": {"files": []}})
    shown = _set(agent, ["launcher"], issued_at=T2)["result"]
    assert shown["slots"][0]["context_files"] == {"files": ["AGENTS.md"], "custom_path": None}
    assert PersonaInstanceStore().get(agent).slot_context_files == {"launcher": ["AGENTS.md"]}
    cleared = _set(agent, ["launcher"], context_files={}, issued_at="2026-11-01T15:00:00+00:00")["result"]
    assert cleared["slots"][0]["context_files"] is None


def test_the_toggles_travel_and_the_custom_path_stays_on_this_machine():
    from agent_runtime.persona_instance_sync.contract import (
        PERSONA_INSTANCE_ALLOWED_KEYS,
        PERSONA_INSTANCE_LOCAL_ONLY_KEYS,
    )

    assert "slot_context_files" in PERSONA_INSTANCE_ALLOWED_KEYS
    assert "slot_context_custom" in PERSONA_INSTANCE_LOCAL_ONLY_KEYS


def test_a_stale_whole_row_write_cannot_revert_a_newer_pick(tmp_path):
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "c"}})
    agent = _instance(workspace)
    store = PersonaInstanceStore()
    held = store.get(agent)
    _set(agent, ["launcher"], context_files={"launcher": {"files": ["CLAUDE.md"]}})
    held.display_name = "settled"
    store.update(held)
    assert store.get(agent).slot_context_files == {"launcher": ["CLAUDE.md"]}


def test_a_namespace_instance_without_the_fields_reads_as_no_override(tmp_path):
    """The loader reads the record through ``getattr`` — an instance shape that predates the fields loads as today."""
    workspace = _workspace(tmp_path, {"launcher": {"CLAUDE.md": "claude rules"}})
    context = load_slot_context(types.SimpleNamespace(workspace_id=workspace, assigned_slots=["launcher"],
                                                      primary_slot=None))
    assert context.content == "## launcher — CLAUDE.md\n\nclaude rules"
