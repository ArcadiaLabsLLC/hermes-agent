"""A shared workspace's Lens monitor is a recipe that runs on this PC only after its person turns
it on (row ``RT-LENS-SHARED-RECIPES-OPT-IN``, ruling ``OR-2026-11-09-lens-shared-recipes-opt-in``).

What workspace sharing carries of Lens today, confirmed 2026-11-10: NOTHING. The store is one
SQLite file per runtime (``store.lens_root()``, the head home), and no sync, remote-adopt or
template module imports the Lens package, so no monitor, Episode or receipt travels. The one
door that writes a monitor (``LensStore.create``) writes a DRAFT, and the only way to ENABLED —
the one state the poller reads (``LensPoller._enabled``) — is the operator's
``runtime.lens.enable``. These gates keep that true when recipe sharing is built:

* a recipe written into this store for another workspace, even sealed, is not polled until
  ``runtime.lens.enable`` — killed by ``LensStore.create`` inserting ``MonitorState.ENABLED``
  (or ``seal`` setting it);
* the only caller of ``set_state`` and the only SQL that moves a monitor's state are the
  operator's RPC and the store itself, and no sync / remote / template module imports Lens —
  killed by adding ``from agent_runtime.lens.store import LensStore`` to
  ``agent_runtime/office_sync.py``.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.store import LensStore, MonitorState

RUNTIME = Path(__file__).resolve().parents[3] / "agent_runtime"
T0 = datetime(2026, 11, 10, 12, tzinfo=UTC)
PUBLIC = ["93.184.216.34"]


def _recipe(monitor_id: str) -> dict:
    feed = {"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
            "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}
    return {"version": 1, "monitor_id": monitor_id, "feeds": [feed], "rules": [],
            "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}, "persona_id": None}


def _enable(monitor_id: str) -> None:
    from agent_runtime import serve_rpc

    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": "runtime.lens.enable",
                                      "params": {"monitor_id": monitor_id}})
    assert "error" not in reply, reply


def test_a_shared_workspaces_recipe_is_not_polled_until_this_pcs_person_enables_it():
    store = LensStore()
    store.create(_recipe("shared"), workspace_id="ws_shared")
    store.seal("shared")  # the whole recipe, sealed as it would arrive: sources, rules, schedule
    reads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reads.append(str(request.url))
        return httpx.Response(200, json={"cpu": 1})

    poller = LensPoller(clock=lambda: T0, client=httpx.Client(transport=httpx.MockTransport(handler)),
                        resolver=lambda host: PUBLIC)

    assert store.get("shared")["state"] == MonitorState.DRAFT.value
    assert poller.tick() == 0 and reads == []

    _enable("shared")
    assert poller.tick() == 1 and reads == ["https://status.example.invalid/health"]


def _sources() -> dict[str, str]:
    return {path.relative_to(RUNTIME.parent).as_posix(): path.read_text(encoding="utf-8")
            for path in RUNTIME.rglob("*.py")}


def test_only_the_operator_rpc_and_the_store_move_a_monitors_state():
    callers, writers = set(), set()
    for name, text in _sources().items():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_state":
                callers.add(name)
        if re.search(r"(UPDATE|INTO)\s+monitors\b", text):
            writers.add(name)
    assert callers <= {"agent_runtime/serve_rpc/lens.py", "agent_runtime/lens/store.py"}, callers
    assert writers == {"agent_runtime/lens/store.py"}, writers


def test_no_sync_remote_or_template_module_reaches_lens():
    """A module that carries a workspace between machines must not write Lens rows: the recipe
    arrives OFF only while nothing synced can reach the store. Sharing a recipe is built as its
    own door that writes a DRAFT, and this list then names it."""

    carriers = re.compile(r"(sync|remote|adopt|template|_take|_merge)")
    reaching, checked = [], set()
    for name, text in _sources().items():
        if name.startswith("agent_runtime/lens/") or not carriers.search(name):
            continue
        checked.add(name)
        for node in ast.walk(ast.parse(text)):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(module == "agent_runtime.lens" or module.startswith("agent_runtime.lens.")
                   or (isinstance(node, ast.ImportFrom) and node.level and module.split(".")[0] == "lens")
                   for module in modules):
                reaching.append(name)
    assert {"agent_runtime/office_sync.py", "agent_runtime/git_remote_adopt.py",
            "agent_runtime/workspace_template.py"} <= checked  # the scan is not empty by accident
    assert reaching == [], reaching
