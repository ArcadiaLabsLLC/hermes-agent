"""A phone Chat rename updates the saved title the operator directory reads.

Killing mutation: omit set_session_title in rename._write_title and the
directory still returns the old title after the RPC.
"""

from contextlib import closing

from agent_runtime import serve_rpc
from agent_runtime.persona_chat_durability import default_persona_session_db
from tests.agent_runtime.test_instance_conversation_owner import chat_head  # noqa: F401 — autouse fixture
from tests.agent_runtime.test_instance_history import OWNER, OTHER, create, read_history
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, placed_agent, qa_persona  # noqa: F401 — fixtures


def _rename(instance, session, **overrides):
    return serve_rpc.handle_request({
        "jsonrpc": "2.0", "id": "rename", "method": "runtime.persona.chat.rename",
        "params": {"session_id": session, "persona_id": PERSONA,
                   "persona_instance_id": instance["persona_instance_id"],
                   "client_scope": OWNER, "title": "  Release   review  ", **overrides},
    })


def test_rename_persists_one_user_title_in_the_directory(placed_agent):
    saved = create(placed_agent, "saved")
    loaded = create(placed_agent, "loaded")
    reply = _rename(placed_agent, saved)

    assert reply["result"]["title"] == "Release review", reply
    rows = {row["session_id"]: row["title"] for row in read_history()["result"]["conversations"]}
    assert rows[saved] == "Release review"
    assert rows[loaded] != rows[saved]
    with closing(default_persona_session_db()) as db:
        assert db.get_session_title_source(saved) == db.TITLE_SOURCE_USER


def test_rename_refuses_wrong_account_wrong_holder_and_empty_title(placed_agent):
    saved = create(placed_agent, "saved")
    for fields, reason in [
        ({"client_scope": OTHER}, "conversation_owner_changed"),
        ({"persona_instance_id": "personainst_someone_else"}, "foreign_chat_session"),
        ({"title": "  "}, "invalid_request"),
    ]:
        refused = _rename(placed_agent, saved, **fields)
        assert refused["error"]["data"]["reason"] == reason, refused
    with closing(default_persona_session_db()) as db:
        assert db.get_session_title(saved) != "Release review"
