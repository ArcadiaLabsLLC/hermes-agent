"""RT-WORK-OBSERVATION-READ: ``observe: true`` on capabilities / list / inspect reads Work without acting.

The ruled lifecycle (create, promote, move the default brain; sync hermes's worktrees) stays on the
ordinary calls. An observation call must make ZERO logical writes: every mutating door is replaced by a
tripwire, and the store's bytes are compared before and after.
"""
from __future__ import annotations

import hashlib

import pytest

from agent_runtime import paths
from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import WorkspaceStore
from agent_runtime.work import service
from agent_runtime.work import store as work_store
from agent_runtime.work_store import default_brain
from agent_runtime.work_store.writer import Writer


def _workspace():
    machine_roots_cache_clear()
    ws = WorkspaceStore().create(name="Desk").id
    surface = paths.office_surface_path(ws)
    surface.parent.mkdir(parents=True, exist_ok=True)
    surface.write_text("{}", encoding="utf-8")
    ensure_install_identity(paths.store_root())
    return ws


def _tree_digest():
    root = paths.store_root()
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "receipts" not in p.parts):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _tripwires(monkeypatch):
    def refuse(name):
        def _raise(*_a, **_k):
            raise AssertionError(f"observation read called the mutating door {name}")
        return _raise

    monkeypatch.setattr(work_store, "normalize_default_brain", refuse("normalize_default_brain"))
    monkeypatch.setattr(default_brain, "ensure_default_brain", refuse("ensure_default_brain"))
    monkeypatch.setattr(Writer, "sync", refuse("Writer.sync"))
    monkeypatch.setattr(Writer, "apply", refuse("Writer.apply"))
    monkeypatch.setattr(Writer, "_ensure_worktree", refuse("Writer._ensure_worktree"))


def _scope(caps, ws):
    owner = next(row for row in caps["owners"] if row["workspace_id"] == ws)
    return {"install_id": caps["install_id"], "owner": owner["owner"], "client_scope": "account"}


def test_observed_capabilities_on_a_fresh_workspace_say_missing_and_create_nothing(monkeypatch):
    ws = _workspace()
    _tripwires(monkeypatch)
    before = _tree_digest()

    caps = service.execute("capabilities", {"observe": True}, STDIO_OWNER)

    assert caps["observe"] == ["capabilities", "list", "inspect"]
    assert caps["default_brain"][ws] == {"state": "missing"}
    assert not (paths.default_brain_dir(ws) / ".git").exists()
    assert _tree_digest() == before


def test_observed_list_and_inspect_read_the_rows_and_write_nothing(monkeypatch):
    ws = _workspace()
    caps = service.execute("capabilities", {}, STDIO_OWNER)  # the ruled lifecycle creates the brain
    scope = _scope(caps, ws)
    task_id = service.execute("start", {**scope, "request_id": "request-1", "title": "Review"},
                              STDIO_OWNER)["task"]["id"]
    full = service.execute("list", scope, STDIO_OWNER)

    _tripwires(monkeypatch)
    before = _tree_digest()
    caps_seen = service.execute("capabilities", {"observe": True}, STDIO_OWNER)
    listing = service.execute("list", {**scope, "observe": True}, STDIO_OWNER)
    (board,) = listing["boards"]
    task = service.execute("inspect", {**scope, "observe": True, "slot": board["slot"], "task_id": task_id},
                           STDIO_OWNER)["task"]

    assert caps_seen["default_brain"][ws]["state"] == "present"
    assert board["readable"] is True and listing["stale"] is False
    assert [row["id"] for q in board["queues"] for row in q["rows"]] == [task_id]
    assert board["queues"] == full["boards"][0]["queues"]
    assert task["id"] == task_id
    assert _tree_digest() == before


def test_an_unread_board_is_listed_unreadable_and_stale_not_silently_empty(monkeypatch):
    ws = _workspace()
    caps = service.execute("capabilities", {}, STDIO_OWNER)
    scope = _scope(caps, ws)
    _tripwires(monkeypatch)  # no full read has cut hermes's worktree yet

    listing = service.execute("list", {**scope, "observe": True}, STDIO_OWNER)

    (board,) = listing["boards"]
    assert board["readable"] is False and board["queues"] == []
    assert listing["stale"] is True


def test_the_ordinary_capabilities_call_still_runs_the_lifecycle():
    ws = _workspace()  # positive control: the same call without observe creates the default brain
    caps = service.execute("capabilities", {}, STDIO_OWNER)
    assert caps["default_brain"][ws]["state"] == "created"
    assert (paths.default_brain_dir(ws) / ".git").is_dir()


@pytest.mark.parametrize("value", ["true", 1, None])
def test_only_a_literal_true_observes(value):
    ws = _workspace()
    caps = service.execute("capabilities", {"observe": value}, STDIO_OWNER)
    assert caps["default_brain"][ws]["state"] == "created"
