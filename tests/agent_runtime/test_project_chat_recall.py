"""Recall across the own store and the Projects' shared stores (plan project-slots-and-shared-chats §6, §10, row RT-PROJECT-CHAT-RECALL-ACROSS-STORES)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from hermes_time import now

from agent_runtime import paths, serve_rpc
from agent_runtime.launcher_invocation import launcher_invocation
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.project_chat_fold import fold
from agent_runtime.project_store import ProjectStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.project_chat_recall import recall_session_search

T0 = "2026-10-29T10:00:00+00:00"
REPO = Path(__file__).resolve().parents[2]


def _instance(instance_id, workspace_id, name):
    PersonaInstanceStore()._write(PersonaInstance(
        id=instance_id, persona_id="dev", role="dev", display_name=name, profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, workspace_id=workspace_id, updated_at=now()))


@pytest.fixture
def world(tmp_path):
    from hermes_state import SessionDB

    store = ProjectStore()
    store.declare("p1", [{"name": "launcher", "repo": {"clone_url": "https://example.com/l.git"}}], issued_at=T0,
                  machine="m", name="Eternia")
    store.set_category("p1", "chats", slot="launcher", subpath=None, shared=True, issued_at=T0)
    workspace = WorkspaceStore().create(name="Team").id
    set_project_connection(workspace, "p1", connected=True, expected_revision=0)
    _instance("personainst_me", workspace, "Me")
    _instance("personainst_alice", workspace, "Alice")
    folder = tmp_path / "chats" / "chat_s"
    folder.mkdir(parents=True)
    (folder / "nekwo-ubuntu24.base.jsonl").write_text(json.dumps({
        "turn_uid": "u1", "seq": 1, "role": "user", "ts": 100.0, "content": "the pineapple deploy runbook",
        "author": {"persona_instance_id": "personainst_alice", "machine_id": "nekwo-ubuntu24"}}) + "\n",
        encoding="utf-8")
    fold("p1", tmp_path / "chats")
    own = SessionDB(db_path=tmp_path / "state.db")
    own.create_session("own_old", "harness")
    own.append_message("own_old", "user", "my pineapple notes")
    own.create_session("cur", "harness")
    own.append_message("cur", "user", "pineapple in the current chat")
    yield own
    own.close()


def _search(own, **kwargs):
    with launcher_invocation("operator", "cur", "turn-1", persona_instance_id="personainst_me"):
        return json.loads(recall_session_search(db=own, current_session_id="cur", **kwargs))


def _recall(enabled):
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": "runtime.persona.instance.recall.set",
                                      "params": {"persona_instance_id": "personainst_me", "enabled": enabled,
                                                 "issued_at": T0}})
    assert reply["result"]["recall_shared_projects"] is enabled


def test_with_the_switch_off_a_shared_hit_never_appears(world):
    found = _search(world, query="pineapple")
    assert [r["session_id"] for r in found["results"]] == ["own_old"]
    assert _search(world, session_id="@project:p1/chat_s")["success"] is False


def test_with_the_switch_on_the_shared_hit_appears_labelled_by_its_author(world):
    _recall(True)
    found = _search(world, query="pineapple")
    by_session = {r["session_id"]: r for r in found["results"]}
    assert set(by_session) == {"own_old", "chat_s"}  # the own current lineage stays excluded
    assert found["results"][0]["session_id"] == "own_old"  # own store first on a tie of rank
    shared = by_session["chat_s"]
    assert shared["shared_from"] == {"project": "Eternia", "project_id": "p1", "author": "Alice",
                                     "machine": "nekwo-ubuntu24"}
    assert shared["link"] == "@project:p1/chat_s"
    assert shared["shared_label"] == "— Alice's agent, on nekwo-ubuntu24"
    read = _search(world, session_id="@project:p1/chat_s")
    assert read["mode"] == "read" and read["messages"][0]["content"] == "the pineapple deploy runbook"
    anchor = read["messages"][0]["id"]
    scroll = _search(world, session_id="@project:p1/chat_s", around_message_id=anchor)
    assert scroll["mode"] == "scroll" and scroll["messages"][0]["id"] == anchor


def test_a_project_whose_chats_stop_sharing_drops_out_of_recall(world):
    _recall(True)
    ProjectStore().set_category("p1", "chats", slot="launcher", subpath=None, shared=False,
                                issued_at="2026-10-29T11:00:00+00:00")
    assert [r["session_id"] for r in _search(world, query="pineapple")["results"]] == ["own_old"]


def test_no_module_but_the_fold_and_recall_opens_the_shared_stores():
    """NEGATIVE source walk: memory extraction and every other reader never name the shared store.

    Positive control: the walk finds the two modules that ARE allowed, so it is reading the tree.
    """
    pattern = re.compile(r"\b(?:project_chat_store_path|open_shared_store|ProjectSharedSessionDB)\b")
    allowed = {"agent_runtime/project_chat_fold.py", "agent_runtime/project_chat_recall.py", "agent_runtime/paths.py"}
    hits = set()
    for root in ("agent_runtime", "agent", "tools", "hermes_cli", "plugins"):
        for path in (REPO / root).rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                hits.add(path.relative_to(REPO).as_posix())
    assert {"agent_runtime/project_chat_fold.py", "agent_runtime/project_chat_recall.py"} <= hits
    assert hits <= allowed, sorted(hits - allowed)
    assert "agent/background_review.py" not in hits


def test_the_agents_registered_tool_call_recalls_across_the_enabled_stores(world):
    """The seam in tools/session_search_tool.py: the registry's handler, not only the fork's door, merges.

    Positive control: with the switch off the same call answers the own store only.
    """
    import tools.session_search_tool  # noqa: F401 — the module whose import registers and routes the tool
    from tools.registry import registry

    handler = registry.get_entry("session_search", scope=None).handler

    def call(args):
        with launcher_invocation("operator", "cur", "turn-1", persona_instance_id="personainst_me"):
            return json.loads(handler(args, db=world, current_session_id="cur"))

    assert [r["session_id"] for r in call({"query": "pineapple"})["results"]] == ["own_old"]
    _recall(True)
    found = call({"query": "pineapple"})
    assert {r["session_id"] for r in found["results"]} == {"own_old", "chat_s"}
    assert next(r for r in found["results"] if r["session_id"] == "chat_s")["shared_from"]["author"] == "Alice"
    read = call({"session_id": "@project:p1/chat_s"})
    assert read["mode"] == "read" and read["messages"][0]["content"] == "the pineapple deploy runbook"
