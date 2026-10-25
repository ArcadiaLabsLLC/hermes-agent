"""Creation, actual execution and retry must preserve the cockpit selection."""
from agent_runtime.persona_assignments import PersonaInstanceStore
from tests.agent_runtime.independent_conversation_peer import Provider, independent_conversation_peer
from tests.waiting import wait_until

OWNER = "a" * 64


def test_completed_native_turns_keep_the_selected_cockpit_root(monkeypatch):
    with independent_conversation_peer(monkeypatch) as peer:
        directory = peer.call("runtime.agent.directory")
        agent = next(a for a in directory["agents"] if a["profile"] == "independent-native" and a["canonical"])
        scope = dict(client_scope=OWNER, install_id=directory["install_id"],
                     persona_id=agent["persona_id"], persona_instance_id=agent["instance_id"])
        selected = peer.call("runtime.persona.instance.open_chat", **scope,
                             new_session=True, idempotency_key="cockpit-default")["session_id"]
        opened = peer.call("runtime.agent.conversation.create", **scope, idempotency_key="ordinary")
        target = {**scope, "session_id": opened["session_id"], "workspace_id": opened.get("workspace_id")}
        assert target["session_id"] != selected
        store = PersonaInstanceStore()
        for index in range(3):
            row = store.get(target["persona_instance_id"])
            assert row.session_id == row.default_chat_session_id == selected
            turn = f"ordinary-{index}"
            sent = peer.call("runtime.operator.conversation.message", **target,
                             turn_request_id=turn, message="Reply briefly. Do not use tools.", stream=True)
            assert sent["accepted"]
            def finished():
                state = peer.call("runtime.operator.conversation.read", **target, turn_request_id=turn)
                assert store.get(target["persona_instance_id"]).default_chat_session_id == selected
                return state if state["delivery_observed"] and not state["active_turns"] and not state["delivery_pending"] else None
            state = wait_until(finished, timeout=60, what="native independent turn to finish")
            assert sum("Local native answer" in m["text"] for m in state["messages"]) == index + 1
            row = store.get(target["persona_instance_id"])
            assert row.session_id == row.default_chat_session_id == selected
        replay = peer.call("runtime.agent.conversation.create", **scope, idempotency_key="ordinary")
        assert replay["session_id"] == target["session_id"] and replay["idempotent_replay"]
    requests = [(auth, body) for auth, body in Provider.requests if body.get("stream")]
    assert len(requests) == 3
    assert all(auth == "Bearer isolated-test" and body["model"] == "test-model" for auth, body in requests)
