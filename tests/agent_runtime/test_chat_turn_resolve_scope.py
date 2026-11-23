"""A caller that names a ``client_scope`` resolves a turn only in a chat that scope owns.

Hermes row ``RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE`` (review w1122d.2) gave
``runtime.chat.turn.resolve`` the send path's own access rule. The computer scope stamping it was written
beside left in ``RT-ACCOUNT-ONLY-A-PHONE-ANSWERS-A-PAIRED-COMPUTER-ONLY-AS-ONE-OF-YOUR-OWN``; the rule stays for
every scoped caller, and this file keeps its test (``test_computer_scope`` was deleted with the stamping).

Killing mutation (red seen 2026-11-23, in a scratch tree): ``chat_verbs.turn_resolve._scope_refusal`` skips its
check, and the resolve naming another scope is answered past it.
"""

from __future__ import annotations

from contextlib import closing

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE
from agent_runtime.persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import fixture

OWNER = "a" * 64
OTHER = "c" * 64


def _ask(params: dict) -> dict:
    name = "runtime.chat.turn.resolve"
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": name, "method": name, "params": params},
                                    serve_rpc.RpcContext(caller=LOCAL_CONSOLE))


def test_a_scoped_resolve_in_a_chat_another_scope_owns_is_refused(tmp_path, monkeypatch):
    target = fixture(tmp_path / "phone", monkeypatch, "Owner")
    instance = target["persona_instance_id"]
    session = f"persona_chat_{instance}_0a0a0a000001"
    with closing(SessionDB(db_path=tmp_path / "phone" / "state.db")) as db:
        db.create_session(session, source=PERSONA_CHAT_SESSION_SOURCE, model_config={"client_scope": OWNER})
        db.append_message(session, "user", "hello")
    resolve = {"session_id": session, "persona_instance_id": instance, "client_message_id": "x", "turn_id": "t",
               "action": "abandon"}
    assert "chat root is not owned by this client scope" in str(_ask({**resolve, "client_scope": OTHER}))
    # The owner's own scope and the unscoped operator pass the scope check (refused later, for the turn).
    for named in ({"client_scope": OWNER}, {}):
        assert "client scope" not in str(_ask({**resolve, **named})), named
