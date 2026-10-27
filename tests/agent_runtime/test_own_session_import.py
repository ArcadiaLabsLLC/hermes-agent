"""``hermes namespace import-sessions`` (row RT-SESSIONS-IMPORT-OWN-EXPORT). Temp roots only.

The reseed shape: a source home's chats are exported the way ``hermes sessions export`` writes
them, then imported into a namespace whose persona instances were re-created, not copied.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime import own_session_import as imp
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_chat_history import persona_chat_history_summary
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState
from hermes_cli import _namespace_bootstrap as ns
from hermes_cli.session_export import export_projection
from hermes_state import SessionDB

REPO = Path(__file__).resolve().parents[2]
ACCT = "acct-0123456789abcdef"
CHAT = "agent_runtime_persona_chat"
#: The target's re-created instances: alice's canonical channel, neko's, and two non-canonical qa ones.
TARGETS = ("personainst_profile_alice", "personainst_neko", "personainst_qa_agent_aaaa1111",
           "personainst_qa_agent_bbbb2222")


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


def _chat(db: SessionDB, sid: str, persona: str, instance: str | None, *, parent: str | None = None,
          root: str | None = None) -> None:
    config = {"mission_chat_root_id": root or sid, "source": CHAT}
    if instance:
        config["persona_instance_id"] = instance
    db.create_session(sid, CHAT, system_prompt=f"Mission Control persona chat for {persona}", model_config=config,
                      parent_session_id=parent)
    db.append_message(sid, "user", f"hello from {sid}")
    db.append_message(sid, "assistant", f"reply in {sid}")


@pytest.fixture
def world(tmp_path: Path) -> dict:
    """A source chat store, its export file, and a seeded-shape target namespace with re-created instances."""
    base = tmp_path / ".hermes"
    base.mkdir()
    env = {"HERMES_DEPENDENCY_ROOT": str(base)}
    item = ns.layout(ACCT, env)
    ns.ensure_manifest(item)
    item.head_home.mkdir(parents=True)  # a seeded namespace's operator home (the seed copies its config)
    (item.head_home / "config.yaml").write_text("model: x\n", encoding="utf-8")
    source = SessionDB(db_path=tmp_path / "source" / "state.db")
    _chat(source, "chat_alice", "profile_alice", "personainst_profile_alice")
    _chat(source, "chat_alice_cont", "profile_alice", "personainst_profile_alice", parent="chat_alice",
          root="chat_alice")
    _chat(source, "chat_neko", "neko", "personainst_neko_agent_1234abcd")  # a retired source instance
    _chat(source, "chat_ghost", "ghost", "personainst_ghost")
    _chat(source, "chat_qa", "qa", "personainst_qa_agent_99990000")
    source.create_session("cli_scratch", "cli")
    source.append_message("cli_scratch", "user", "not a persona chat")
    export = tmp_path / "base-chats.jsonl"
    rows = source.export_all(source=None, **export_projection(False))
    export.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows) + "{not json\n",
                      encoding="utf-8")
    source.close()
    return {"env": env, "item": item, "export": export, "source_db": tmp_path / "source" / "state.db"}


def _recreate_instances(item: ns.Layout, ids: tuple[str, ...] = TARGETS) -> list[PersonaInstance]:
    folder = item.store_root / "persona_instances"
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for instance_id in ids:
        persona = instance_id.removeprefix("personainst_").split("_agent_")[0]
        row = PersonaInstance(id=instance_id, persona_id=persona, role=persona, display_name=persona,
                              profile_id=None, runtime_root=str(item.store_root), state=WorkerSessionState.IDLE)
        (folder / f"{instance_id}.json").write_text(json.dumps(to_jsonable(row)), encoding="utf-8")
        out.append(row)
    return out


def _target_db(item: ns.Layout) -> SessionDB:
    return SessionDB(db_path=item.head_home / "state.db")


def _bound(item: ns.Layout) -> dict[str, str]:
    db = _target_db(item)
    try:
        return {row["id"]: json.loads(row["model_config"] or "{}").get("persona_instance_id")
                for row in db.search_sessions(source=None, limit=1000)}
    finally:
        db.close()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_reseed_import_rebinds_each_chat_and_the_console_lists_it_under_that_instance(world):
    item, before = world["item"], _digest(world["source_db"])
    instances = _recreate_instances(item)
    report = imp.import_into_namespace(ACCT, world["export"], world["env"])
    assert report["namespace"] == ACCT and report["target_store"] == str(item.head_home / "state.db")
    how = {row["session_id"]: row["bound_by"] for row in report["imported"]}
    assert how == {"chat_alice": "same_instance", "chat_alice_cont": "same_instance",
                   "chat_neko": "persona_channel", "cli_scratch": "not_a_persona_chat"}
    skipped = {row.get("session_id") or f"line {row['line']}": row["reason"] for row in report["skipped"]}
    assert skipped == {"chat_ghost": "no_target_instance", "chat_qa": "ambiguous_target", "line 7": "unparseable_line"}
    assert report["counts"] == {"sessions": 6, "imported": 4, "skipped": 3}
    assert _bound(item) == {"chat_alice": "personainst_profile_alice", "chat_alice_cont": "personainst_profile_alice",
                            "chat_neko": "personainst_neko", "cli_scratch": None}
    db = _target_db(item)
    try:  # what the Agent Console reads: the persona's chat directory, per instance
        rows = persona_chat_history_summary(persona_instances=instances, session_db=db)
        assert {row["session_id"]: row["persona_instance_id"] for row in rows} == {
            "chat_alice": "personainst_profile_alice", "chat_neko": "personainst_neko"}
        assert {row["session_id"]: row["message_count"] for row in rows}["chat_alice"] == 4  # root + continuation
    finally:
        db.close()
    assert _digest(world["source_db"]) == before  # the source is only ever read


def test_a_second_import_of_the_same_export_creates_no_duplicate(world):
    item = world["item"]
    _recreate_instances(item)
    imp.import_into_namespace(ACCT, world["export"], world["env"])
    again = imp.import_into_namespace(ACCT, world["export"], world["env"])
    assert again["counts"]["imported"] == 0
    assert again["skipped_by_reason"] == {"already_present": 4, "ambiguous_target": 1, "no_target_instance": 1,
                                          "unparseable_line": 1}
    assert len(_bound(item)) == 4


def test_a_title_the_target_already_holds_imports_suffixed_instead_of_aborting(tmp_path, world):
    """Owner 2026-10-20: the real reseed died on ``UNIQUE constraint failed: sessions.title``
    (two exported chats titled alike, plus the namespace's own fresh "… chat")."""
    item = world["item"]
    _recreate_instances(item)
    source = SessionDB(db_path=tmp_path / "titled" / "state.db")
    for sid in ("chat_t1", "chat_t2"):
        _chat(source, sid, "profile_alice", "personainst_profile_alice")
    source.set_session_title("chat_t1", "Alice chat")
    export = tmp_path / "titled.jsonl"
    rows = source.export_all(source=None, **export_projection(False))
    rows = [{**r, "title": "Alice chat"} if r.get("id") == "chat_t2" else r for r in rows]  # a repeat in the export
    export.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    source.close()
    target = _target_db(item)
    try:  # the namespace already minted one by that title
        _chat(target, "native_alice", "profile_alice", "personainst_profile_alice")
        target.set_session_title("native_alice", "Alice chat")
    finally:
        target.close()
    report = imp.import_into_namespace(ACCT, export, world["env"])
    assert report["counts"]["imported"] == 2, report
    db = _target_db(item)
    try:
        titles = {sid: (db.get_session(sid) or {}).get("title") for sid in ("native_alice", "chat_t1", "chat_t2")}
    finally:
        db.close()
    assert titles == {"native_alice": "Alice chat", "chat_t1": "Alice chat (chat_t1)", "chat_t2": "Alice chat (chat_t2)"}


def test_bind_resolves_an_ambiguous_persona_and_a_bind_to_nowhere_refuses_before_writing(world):
    item = world["item"]
    _recreate_instances(item)
    with pytest.raises(imp.ImportRefused) as refused:
        imp.import_into_namespace(ACCT, world["export"], world["env"], binds={"qa": "personainst_nowhere"})
    assert refused.value.reason is imp.Refusal.BIND_TARGET_UNKNOWN
    assert not (item.head_home / "state.db").exists()
    report = imp.import_into_namespace(ACCT, world["export"], world["env"],
                                       binds=imp.parse_binds(["qa=personainst_qa_agent_bbbb2222"]))
    assert {r["session_id"]: r["bound_by"] for r in report["imported"]}["chat_qa"] == "bind"
    assert _bound(item)["chat_qa"] == "personainst_qa_agent_bbbb2222"
    for bad in (["qa"], ["qa=a", "qa=b"], ["=x"]):
        with pytest.raises(imp.ImportRefused):
            imp.parse_binds(bad)


def test_no_target_instance_or_the_base_root_refuses_and_a_dry_run_writes_nothing(world):
    item, env = world["item"], world["env"]
    with pytest.raises(imp.ImportRefused) as refused:
        imp.import_into_namespace(ACCT, world["export"], env)
    assert refused.value.reason is imp.Refusal.NO_TARGET_INSTANCES
    with pytest.raises(ns.NamespaceRefused) as base:
        imp.import_into_namespace("base", world["export"], env)
    assert base.value.reason is ns.Reason.RESERVED
    _recreate_instances(item)
    planned = imp.import_into_namespace(ACCT, world["export"], env, dry_run=True)
    assert planned["dry_run"] is True and planned["counts"] == {"sessions": 6, "imported": 4, "skipped": 3}
    assert not (item.head_home / "state.db").exists()


def test_the_cli_verb_prints_one_json_object_and_exits_2_on_a_refusal(world):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_NAMESPACE")}
    env.update(world["env"])

    def run(*args):
        return subprocess.run([sys.executable, "-m", "hermes_cli.main", "namespace", "import-sessions", *args],
                              cwd=REPO, env=env, capture_output=True, text=True, timeout=180, check=False)

    refused = run(ACCT, str(world["export"]))
    assert refused.returncode == 2, refused.stderr[-2000:]
    assert json.loads(refused.stdout)["reason"] == "import_no_target_instances"
    _recreate_instances(world["item"])
    done = run(ACCT, str(world["export"]), "--bind", "qa=personainst_qa_agent_aaaa1111")
    assert done.returncode == 0, done.stderr[-2000:]
    assert json.loads(done.stdout)["counts"]["imported"] == 5


def _ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    db = SessionDB(db_path=path, read_only=True)
    try:
        return {row["id"] for row in db.search_sessions(source=None, limit=1000)}
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["per_profile", "process"])
def test_a_chat_bound_to_a_per_profile_instance_lands_in_that_instances_head(tmp_path, world, kind):
    """RT-CHAT-HEAD-OWN-IMPORT-WRITER. Positive control: the same row stamped ``process`` lands in the process store."""
    alice_home = tmp_path / "profiles" / "alice"
    alice_home.mkdir(parents=True)
    instances = _recreate_instances(world["item"])
    instances[0].chat_head_home, instances[0].chat_head_kind = str(alice_home), kind
    process = SessionDB(db_path=tmp_path / "process" / "state.db")
    try:
        report = imp.import_own_export(world["export"], session_db=process, instances=instances)
    finally:
        process.close()
    alice_chats = {"chat_alice", "chat_alice_cont"}  # the root and its continuation, one store
    if kind == "per_profile":
        assert _ids(alice_home / "state.db") == alice_chats
        assert report["per_profile_stores"] == [str(alice_home / "state.db")]
        assert not alice_chats & _ids(tmp_path / "process" / "state.db")
    else:
        assert _ids(alice_home / "state.db") == set()
        assert alice_chats <= _ids(tmp_path / "process" / "state.db")
    assert {"chat_neko", "cli_scratch"} <= _ids(tmp_path / "process" / "state.db")
