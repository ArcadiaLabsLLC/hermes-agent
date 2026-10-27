"""RT-CHAT-HEAD-CH4-CROSS-AGENT-READS — cross-agent chat reads fan out over the heads.

Plan: ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md``
§2.4: reads that list chats across agents group instances by head and open each
``state.db`` once, read-only, through ``chat_session_scope``.
"""

from __future__ import annotations

from contextlib import closing

import pytest

from agent_runtime import chat_session_scope, paths
from agent_runtime.chat_session_scope import SessionDbAccess, resolve_process_chat_scope
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.instance_history import list_instance_conversations
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE, CHAT_HEAD_KIND_PROCESS
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import ensure_persona_chat_session
from agent_runtime.persona_chat_history.summary import persona_chat_history_summary
from agent_runtime.projection_accountant import ProjectionAccountant

BASE_ROOT = "persona_chat_personainst_dev_00000000000a"
ALICE_ROOTS = ("persona_chat_personainst_qa_00000000000b", "persona_chat_personainst_ops_00000000000c")
#: An older, UNBOUND chat of ``qa`` in alice: only the head's own pool can find it.
ALICE_OLDER = "persona_chat_personainst_qa_00000000000d"


@pytest.fixture
def heads(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    base, alice = root / "profiles" / "base", root / "profiles" / "alice"
    for path in (root / "agent-runtime", base, alice):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root / "agent-runtime"))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    return {"base": base, "alice": alice}


def _chat(home, persona_id: str, session_id: str, text: str) -> None:
    from hermes_state import SessionDB

    with closing(SessionDB(db_path=home / "state.db")) as db:
        ensure_persona_chat_session(session_db=db, session_id=session_id, persona_id=persona_id,
                                    title=f"{persona_id} chat", required=True)
        db.append_message(session_id=session_id, role="user", content=text)


def _agents(heads, alice_kind: str):
    """``dev`` in base; ``qa`` and ``ops`` both stamped on the ONE head ``alice``."""

    store = PersonaInstanceStore()
    _chat(heads["alice"], "qa", ALICE_OLDER, "older qa")
    store.open_chat(persona_id="dev", session_id=BASE_ROOT)
    _chat(heads["base"], "dev", BASE_ROOT, "from base")
    for persona_id, root in zip(("qa", "ops"), ALICE_ROOTS):
        instance = store.open_chat(persona_id=persona_id, session_id=root)
        instance.chat_head_home, instance.chat_head_kind = str(heads["alice"]), alice_kind
        store.update(instance)
        _chat(heads["alice"], persona_id, root, f"from alice {persona_id}")
    return store.list_all()


@pytest.fixture
def opens(monkeypatch):
    """Every READ open of a chat store, by db path."""

    seen: list[str] = []
    real = chat_session_scope.open_chat_session_db

    def counted(scope=None, *, access):
        if SessionDbAccess(access) is SessionDbAccess.READ:
            seen.append(str((scope or resolve_process_chat_scope()).db_path))
        return real(scope, access=access)

    monkeypatch.setattr(chat_session_scope, "open_chat_session_db", counted)
    return seen


def _summary(instances):
    accountant = ProjectionAccountant("persona_chat_history")
    with closing(chat_session_scope.open_chat_session_db(access=SessionDbAccess.READ)) as db:
        rows = persona_chat_history_summary(persona_instances=instances, session_db=db, accountant=accountant)
    return {row["session_id"]: row for row in rows}, accountant


def test_the_roster_reads_each_agents_chat_from_its_own_head_opening_each_head_once(heads, opens):
    rows, _ = _summary(_agents(heads, CHAT_HEAD_KIND_PER_PROFILE))

    assert set(rows) == {BASE_ROOT, ALICE_OLDER, *ALICE_ROOTS}
    assert rows[ALICE_ROOTS[0]]["messages"][-1]["text"] == "from alice qa"
    assert rows[BASE_ROOT]["messages"][-1]["text"] == "from base"
    assert opens.count(str(heads["alice"] / "state.db")) == 1


def test_positive_control_process_records_read_only_the_process_head(heads, opens):
    """Same chats, one variable changed: the kind. Alice's store is never opened."""

    rows, accountant = _summary(_agents(heads, CHAT_HEAD_KIND_PROCESS))

    assert set(rows) == {BASE_ROOT}
    assert str(heads["alice"] / "state.db") not in opens


def test_a_per_profile_head_that_is_gone_is_a_typed_drop_never_a_base_read(heads):
    import shutil

    instances = _agents(heads, CHAT_HEAD_KIND_PER_PROFILE)
    shutil.rmtree(heads["alice"])

    rows, accountant = _summary(instances)

    assert set(rows) == {BASE_ROOT}
    assert accountant.summary()["reasons"].get(chat_session_scope.CHAT_HEAD_MISSING) == 2


def test_the_history_list_merges_every_head_newest_first(heads, opens):
    _agents(heads, CHAT_HEAD_KIND_PER_PROFILE)
    install = ensure_install_identity(paths.store_root()).install_id

    page = list_instance_conversations({"install_id": install, "all_accounts": True, "limit": 50})

    assert {row["session_id"] for row in page["conversations"]} == {BASE_ROOT, ALICE_OLDER, *ALICE_ROOTS}
    preview = {row["session_id"]: row["last_message_preview"] for row in page["conversations"]}
    assert preview[ALICE_ROOTS[1]] == "from alice ops"
    assert opens.count(str(heads["alice"] / "state.db")) == 1


def test_the_merge_is_the_one_stores_keyset_order_and_a_head_copy_wins():
    from agent_runtime.instance_history import _merged_pages

    head = [{"id": "b", "started_at": 3.0}, {"id": "dup", "started_at": 1.0}]
    process = [{"id": "c", "started_at": 3.0}, {"id": "dup", "started_at": 1.0}, {"id": "n", "started_at": None}]

    merged = _merged_pages([("head", head), ("process", process)], limit=3)

    assert [(source, row["id"]) for source, row in merged] == [
        ("process", "c"), ("head", "b"), ("head", "dup"), ("process", "n")]
