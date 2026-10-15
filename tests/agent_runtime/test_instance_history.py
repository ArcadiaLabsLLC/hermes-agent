"""Native catalog isolation and stable paging through the actual RPC dispatcher."""
from contextlib import closing

from agent_runtime import paths, serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_chat_durability import default_persona_session_db
from tests.agent_runtime.test_instance_conversation_owner import chat_head as chat_head
from tests.agent_runtime.test_serve_rpc_open_chat import (
    PERSONA, _call, _device, qa_persona as qa_persona, placed_agent as placed_agent,
)

OWNER, OTHER = "a" * 64, "b" * 64


def create(instance, key, owner=OWNER):
    return _call(dict(persona_id=PERSONA, persona_instance_id=instance["persona_instance_id"],
                      new_session=True, idempotency_key=key,
                      **({"client_scope": owner} if owner is not None else {})))["result"]["session_id"]


def read_history(*, caller=LOCAL_CONSOLE, **params):
    install = ensure_install_identity(paths.store_root()).install_id
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "history",
        "method": "runtime.operator.conversation.list", "params": {
            "install_id": install, "client_scope": OWNER, **params}},
        serve_rpc.RpcContext(caller=caller))


def test_filter_precedes_page_bound_and_cursor_survives_new_conversations(placed_agent):
    seeded = {row["session_id"] for row in read_history(all_accounts=True)["result"]["conversations"]}
    own = {create(placed_agent, str(i)) for i in range(3)}
    others = {create(placed_agent, str(i), OTHER) for i in range(7)}
    legacy = create(placed_agent, "legacy", None)
    page = read_history(limit=1)["result"]
    first = page["conversations"][0]
    assert first["session_id"] in own
    assert first["client_scope"] == OWNER and first["available"]
    assert first["persona_instance_id"] == placed_agent["persona_instance_id"]
    found = [first["session_id"]]
    # Concurrent creation cannot shift offset-based pages and repeat a row.
    newest = create(placed_agent, "newest")
    cursor = page["next_cursor"]
    while cursor:
        page = read_history(limit=1, before=cursor)["result"]
        found.extend(row["session_id"] for row in page["conversations"])
        cursor = page["next_cursor"]
    assert len(found) == len(set(found)) and set(found) == own
    rows = read_history(all_accounts=True)["result"]["conversations"]
    assert {row["session_id"] for row in rows} == seeded | own | others | {legacy, newest}
    assert {row.get("client_scope") for row in rows} == {OWNER, OTHER, None}
    with closing(default_persona_session_db()) as db:
        db.append_message(first["session_id"], role="user", content="Keep this history")
    refreshed = read_history()["result"]["conversations"]
    assert next(row for row in refreshed if row["session_id"] == first["session_id"])["message_count"] == 1
    assert all("messages" not in row for row in refreshed)
    # A removed agent leaves readable history, never a replacement attachment.
    instance_path = paths.persona_instances_dir() / (placed_agent["persona_instance_id"] + ".json")
    instance_path.unlink()
    retired = read_history()["result"]["conversations"]
    assert {row["session_id"] for row in retired} == own | {newest}
    assert all(not row["available"] for row in retired)
    assert all(row["persona_instance_id"] == placed_agent["persona_instance_id"] for row in retired)


def test_history_requires_console_and_cursors_cannot_cross_account_or_install(placed_agent):
    create(placed_agent, "one")
    create(placed_agent, "two")
    for params in ({}, {"all_accounts": True}):
        assert "error" in read_history(caller=_device("read"), **params)
    cursor = read_history(limit=1)["result"]["next_cursor"]
    for changed in ({"client_scope": OTHER}, {"all_accounts": True}):
        result = read_history(before=cursor, **changed)
        assert result["error"]["data"]["reason"] == "invalid_history_cursor"
    assert read_history(install_id="other")["error"]["data"]["reason"] == "installation_changed"
    assert read_history(client_scope=None)["error"]["data"]["reason"] == "invalid_client_scope"
    assert read_history(before="[0]")["error"]["data"]["reason"] == "invalid_history_cursor"


def test_unowned_history_without_metadata_requires_all_accounts(placed_agent):
    session = create(placed_agent, "unassigned", None)
    with closing(default_persona_session_db()) as db:
        db._write_sql("UPDATE sessions SET model_config=NULL WHERE id=?", (session,))
    assert session not in {row["session_id"] for row in read_history()["result"]["conversations"]}
    rows = read_history(all_accounts=True)["result"]["conversations"]
    row = next(row for row in rows if row["session_id"] == session)
    assert row.get("client_scope") is None
    assert row["persona_instance_id"] == placed_agent["persona_instance_id"]
    assert row["available"]
