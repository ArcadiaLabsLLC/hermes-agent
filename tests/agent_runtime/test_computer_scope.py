"""A computer at Run chats acts only under its grant's own chat scope, never the phone owner's.

Hermes row ``RT-FU-A-COMPUTER-SENDS-ONLY-UNDER-ITS-OWN-CHAT-SCOPE`` (review w1122d.2): a request's
``client_scope`` is self-declared, so the dispatcher stamps the grant's scope
(``reverse_lane.grants.computer_client_scope``) over it on every verb that states ``computer_scoped``.
The three writes the Look / Run chats rulings say cannot happen are each refused here, and the
computer's own send, steer and attach still work (its own new chat: ``test_instance_history``).

Killing mutations (recorded red in the row's close):

* ``serve_rpc.dispatch.bind_computer_scope`` returns the params unstamped: the send naming the
  owner's scope and the send naming none are answered;
* ``chat_verbs.turn_resolve._scope_refusal`` skips its check: the turn resolve in the owner's chat
  is answered past the scope check.
"""

from __future__ import annotations

from contextlib import closing

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import CALLER_COMPUTER, LOCAL_CONSOLE, TRANSPORT_GATEWAY, RpcCaller
from agent_runtime.persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from agent_runtime.reverse_lane.grants import computer_client_scope
from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import fixture

COMPUTER = RpcCaller(kind=CALLER_COMPUTER, connection_key="lane-1", transport=TRANSPORT_GATEWAY,
                     computer_id="cmp-far", computer_grant="chat")
OWNER = "a" * 64        # the phone owner's scope, as Look's history rows once carried it
ACCOUNT_KEY = "c" * 64  # what the computer's Eternia names: its own account key


def _chats(tmp_path, monkeypatch):
    target = fixture(tmp_path / "phone", monkeypatch, "Owner")
    instance = target["persona_instance_id"]
    owners, mine = (f"persona_chat_{instance}_{suffix}" for suffix in ("0a0a0a000001", "c0ffee000001"))
    with closing(SessionDB(db_path=tmp_path / "phone" / "state.db")) as db:
        for session, scope in ((owners, OWNER), (mine, computer_client_scope(COMPUTER.computer_id))):
            db.create_session(session, source=PERSONA_CHAT_SESSION_SOURCE, model_config={"client_scope": scope})
            db.append_message(session, "user", "hello")
    return target, owners, mine


def _ask(name, params, *, caller=COMPUTER, spawned=None):
    context = serve_rpc.RpcContext(caller=caller, spawn_chat_turn=(
        None if spawned is None else (lambda *args: spawned.append(args))))
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": name, "method": name, "params": params}, context)


def _send(target, session, named, turn):
    return {"persona_id": target["persona_id"], "persona_instance_id": target["persona_instance_id"],
            "session_id": session, "message": "hi", "turn_request_id": turn, **named}


def test_a_run_chats_computer_cannot_send_into_the_phone_owners_chat(tmp_path, monkeypatch):
    target, owners, _ = _chats(tmp_path, monkeypatch)
    spawned = []
    # (1) naming the phone owner's scope, (2) naming none: each is stamped with the grant's and refused.
    for named in ({"client_scope": OWNER}, {}):
        for verb in ("runtime.chat.message", "runtime.chat.steer"):
            frame = _ask(verb, _send(target, owners, named, f"{verb}-{len(named)}"), spawned=spawned)
            assert frame.get("error", {}).get("data", {}).get("reason") == "conversation_owner_changed", (
                verb, named, frame)
    assert spawned == []


def test_a_run_chats_computer_cannot_resolve_a_turn_in_the_phone_owners_chat(tmp_path, monkeypatch):
    target, owners, _ = _chats(tmp_path, monkeypatch)
    resolve = {"session_id": owners, "persona_instance_id": target["persona_instance_id"],
               "client_message_id": "x", "turn_id": "t", "action": "abandon"}
    # (3) with the ids a Look read hands over, naming the owner's scope or none.
    for named in ({"client_scope": OWNER}, {}):
        frame = _ask("runtime.chat.turn.resolve", {**resolve, **named})
        assert "chat root is not owned by this client scope" in str(frame), (named, frame)
    # The phone's own Eternia keeps the unscoped path: refused for the turn, never for a scope.
    assert "client scope" not in str(_ask("runtime.chat.turn.resolve", resolve, caller=LOCAL_CONSOLE))


def test_a_run_chats_computers_own_send_and_attach_still_work(tmp_path, monkeypatch):
    target, _, mine = _chats(tmp_path, monkeypatch)
    spawned = []
    for named in ({"client_scope": ACCOUNT_KEY}, {}):
        sent = _ask("runtime.chat.message", _send(target, mine, named, f"own-{len(named)}"), spawned=spawned)
        assert "result" in sent, (named, sent)
    assert len(spawned) == 2
    attach = {key: target[key] for key in ("install_id", "persona_id", "persona_instance_id", "workspace_id")}
    read = _ask("runtime.operator.conversation.read", {**attach, "session_id": mine, "client_scope": ACCOUNT_KEY})
    assert read["result"]["messages"][-1]["text"] == "hello", read
