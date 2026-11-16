"""The Lens store keeps ONE revision, moved once by every change, carried on every answer and event.

``RT-LENS-STORE-HAS-ONE-REVISION`` (Eternia ``TASK-LENS-READS-FROM-ONE-STORE``, subtask 8.1). Eternia
re-reads a Lens slice only when ``store_revision`` moved past the one the slice was read at, so a
change that does not move it leaves a panel stale, and a read that moves it re-reads for nothing.

The writers are enumerated from the store's own write entry: every ``LensStore._db`` transaction a
broad journey opens is recorded with the function that opened it, and each must have moved the
revision by exactly one when it changed a row and by zero when it did not. A writer on its own
connection to ``lens.sqlite3`` is found from the source (any non-read-only ``sqlite3.connect`` in a
module that names the Lens store path) and must call ``bump_store_revision``.

Killing mutations (red recorded in the change commit):
* drop the bump from ``LensStore._db`` -> ``test_every_store_transaction_moves_the_revision_once_when_it_changed``
  names each writer (``seal``, ``record``, ``save_receipt``, ``record_evidence``, ...);
* drop ``on_change`` from ``recipe_shelf.LENS_RECIPE_FAMILY`` -> the shelf test reds on the share and the pull;
* drop the ``bump_store_revision`` call from ``realm_rekey_outside._rekey_lens`` -> the source test names
  ``agent_runtime/realm_rekey_outside.py`` and the re-key test reds.
"""

from __future__ import annotations

import ast
import inspect
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.lens import recipe_shelf
from agent_runtime.lens.episode import Episode, EpisodeState
from agent_runtime.lens.recipe_shelf import LENS_RECIPE_FAMILY, recipe_document
from agent_runtime.lens.revision import lens_revision, read_store_revision
from agent_runtime.lens.store import LensStore, ReceiptOutcome, to_ms
from agent_runtime.lens.store_proposals import record_evidence
from agent_runtime.realm_sync.document_family import DocumentStore, apply_document_pull

RUNTIME = Path(__file__).resolve().parents[3] / "agent_runtime"
T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)
WORKSPACE = "ws_team"


def _manifest(monitor_id: str = "status") -> dict:
    return {"version": 1, "monitor_id": monitor_id,
            "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                       "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}],
            "rules": [], "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0},
            "persona_id": None}


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert "result" in reply, reply
    return reply["result"]


def _lens_events() -> list[tuple[str, dict]]:
    return [(evt.type, evt.payload) for _, evt in EventLog().iter_from_offset(0) if evt.type.startswith("lens.")]


@contextmanager
def _recording(monkeypatch):
    """Record every ``LensStore._db`` transaction: (opener, changed a row, revision moved by)."""

    original = LensStore._db
    seen: list[tuple[str, bool, int]] = []

    @contextmanager
    def recorded(self):
        opener = next(frame.function for frame in inspect.stack()[2:] if frame.function not in
                      {"__enter__", "recorded", "connection", "_db"})
        before = read_store_revision(self.path)
        with original(self) as conn:
            start = conn.total_changes
            yield conn
            changed = conn.total_changes != start
        seen.append((opener, changed, read_store_revision(self.path) - before))

    monkeypatch.setattr(LensStore, "_db", recorded)
    yield seen


def test_every_store_transaction_moves_the_revision_once_when_it_changed(isolate_agent_runtime_root, monkeypatch):
    with _recording(monkeypatch) as seen:
        _rpc("runtime.lens.create", {"manifest": _manifest(), "workspace_id": WORKSPACE})
        _rpc("runtime.lens.seal", {"monitor_id": "status"})
        _rpc("runtime.lens.enable", {"monitor_id": "status"})
        _rpc("runtime.lens.list", {})
        _rpc("runtime.lens.get", {"monitor_id": "status"})
        _rpc("runtime.lens.budget.get", {"monitor_id": "status"})
        store = LensStore()
        store.record("status", "api", observed_at=T0, received_at=T0, value=1.0, reason="ok")
        store.latest("status", "api")
        episode = Episode(monitor_id="status", rule_id="cpu_hot", ordinal=1, first_seen=T0, last_seen=T0,
                          count=1, state=EpisodeState.ACTIVE)
        store.save_episode(episode)
        store.save_episode(replace(episode, last_seen=T0 + timedelta(seconds=1), count=2))  # a tick writes too
        receipt = {"episode_id": episode.id, "monitor_id": "status", "turn_id": f"lens-episode-{episode.id}",
                   "started_ms": to_ms(T0), "outcome": ReceiptOutcome.FORGING.value, "tool_admission": "read_only"}
        store.save_receipt(receipt, episode=replace(episode, turn_id=receipt["turn_id"]))
        store.finish_receipt(episode.id, outcome=ReceiptOutcome.FORGED.value, finished_ms=to_ms(T0) + 1)
        record_evidence(store, "status", "digest-1", {"kind": "test"})
        store.mark_shared("status", "hash-1")
        _rpc("runtime.lens.pause", {"monitor_id": "status"})
        _rpc("runtime.lens.receipts", {"monitor_id": "status"})

    wrong = [(opener, changed, moved) for opener, changed, moved in seen if moved != (1 if changed else 0)]
    assert not wrong, f"writers that did not move the Lens store revision exactly once: {wrong}"
    writers = {opener for opener, changed, _ in seen if changed}
    assert {"create", "seal", "set_state", "record", "move_episode", "save_receipts", "finish_receipt",
            "record_evidence", "mark_shared"} <= writers, writers
    assert any(not changed for _, changed, _ in seen), "the journey must include reads that move nothing"


def test_every_answer_and_event_carries_the_revision(isolate_agent_runtime_root):
    assert _rpc("runtime.lens.list", {})["store_revision"] == 0  # no store yet
    created = _rpc("runtime.lens.create", {"manifest": _manifest()})
    sealed = _rpc("runtime.lens.seal", {"monitor_id": "status"})
    # Read BEFORE the verb ran: never newer than what the answer shows.
    assert sealed["store_revision"] == created["store_revision"] + 1
    after = LensStore().store_revision()
    assert _rpc("runtime.lens.get", {"monitor_id": "status"})["store_revision"] == after
    assert _rpc("runtime.lens.get", {"monitor_id": "status"})["store_revision"] == after  # a read moves nothing

    events = [body for kind, body in _lens_events() if kind == "lens.monitor.changed"]
    assert [(body["change"], body["store_revision"]) for body in events] == [("draft", after - 1), ("sealed", after)]


def test_a_shelf_write_and_a_realm_pull_move_the_revision(isolate_agent_runtime_root, tmp_path):
    shelf = DocumentStore(LENS_RECIPE_FAMILY)
    document = recipe_document(WORKSPACE, _manifest("site-health"))
    token = f"{WORKSPACE}/site-health"

    start = lens_revision()
    recipe_shelf.write_recipe(document)
    assert lens_revision() == start + 1
    recipe_shelf.write_recipe(document)  # the same bytes: nothing changed
    assert lens_revision() == start + 1
    shelf.clear(token)
    assert lens_revision() == start + 2

    # The generic realm pull adopts through the same door, so a pulled recipe moves it too.
    subtree = tmp_path / "subtree"
    published = LENS_RECIPE_FAMILY.published_root(subtree) / WORKSPACE / "site-health.json"
    published.parent.mkdir(parents=True)
    published.write_bytes(document)
    summary = apply_document_pull(LENS_RECIPE_FAMILY, "realm_a", subtree)
    assert summary.adopted == [token]
    assert lens_revision() == start + 3
    assert paths.lens_recipe_path(WORKSPACE, "site-health").read_bytes() == document

    shared = recipe_shelf.read_recipe(WORKSPACE, "site-health")
    recipe_shelf.announce(shared, recipe_shelf.RecipeChange.SHARED)
    events = [body for kind, body in _lens_events() if kind == "lens.recipe.changed"]
    assert events[-1]["store_revision"] == start + 3


def test_a_realm_rekey_of_the_lens_store_moves_the_revision(isolate_agent_runtime_root):
    from agent_runtime.realm_rekey_outside import _rekey_lens

    LensStore().create(_manifest(), workspace_id="ws_old")
    before = lens_revision()
    _rekey_lens(SimpleNamespace(workspaces={"ws_old": "ws_new"}))
    assert LensStore().get("status")["workspace_id"] == "ws_new"
    assert lens_revision() == before + 1
    _rekey_lens(SimpleNamespace(workspaces={"ws_absent": "ws_other"}))  # changed nothing
    assert lens_revision() == before + 1


def _names_lens_store_path(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("lens.store"):
            if any(alias.name in {"default_path", "lens_root"} for alias in node.names):
                return True
    return False


def _writes_through_its_own_connection(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connect"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "sqlite3"):
            if "mode=ro" not in ast.unparse(node):
                return True
    return False


def test_every_writer_on_its_own_connection_to_the_lens_store_bumps_the_revision():
    """Enumerated from the source, not a list: a module that resolves the Lens store's path and opens
    a writable ``sqlite3`` connection writes ``lens.sqlite3`` beside ``LensStore._db``."""

    own = set()
    for path in RUNTIME.rglob("*.py"):
        name = path.relative_to(RUNTIME.parent).as_posix()
        if name in {"agent_runtime/lens/store.py", "agent_runtime/lens/revision.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _names_lens_store_path(tree) and _writes_through_its_own_connection(tree):
            own.add(name)
            calls = {node.func.id for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
            assert "bump_store_revision" in calls, f"{name} writes the Lens store and never bumps its revision"
    assert "agent_runtime/realm_rekey_outside.py" in own, own  # the census still finds the known one


def test_the_revision_is_read_from_the_store_file_and_survives_a_new_store_object(isolate_agent_runtime_root):
    LensStore().create(_manifest())
    revision = LensStore().store_revision()
    assert revision >= 1
    assert json.dumps({"store_revision": revision})  # an integer on the wire
    assert LensStore().store_revision() == revision
