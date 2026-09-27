"""Real native and compute execution: reopen questions/streaming, answer, exact Stop."""
import pytest

from agent_runtime.conversations.model import ConversationError, ConversationScope, Refusal
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.native_recovery_provider import RecoveryProvider, until

pytestmark = pytest.mark.timeout(120)


@pytest.mark.parametrize("compute", [False, True], ids=["inline", "compute-child"])
def test_reopen_live_question_and_stream_then_stop_same_execution(tmp_path, compute):
    home = tmp_path / "profile"
    home.mkdir()
    provider = RecoveryProvider()
    provider.configure(home, compute=compute)
    service = ConversationService(tmp_path, "isolated", profile_home=lambda _: home)
    scope = ConversationScope("operator", "account", "profile")
    def open_():
        return service.open(scope, key="same-chat", cwd=str(tmp_path), expected_home=str(home))
    try:
        sid = open_()["session_id"]
        service.send(scope, sid, "original", {"text": "Ask whether to continue.", "images": []})
        recovered = until(open_, lambda page: bool(page["recovery"].get("open_requests")))
        question = recovered["recovery"]["open_requests"][0]
        assert question["method"] == "clarify"
        assert recovered["turn"]["turn_id"] == "original"
        execution_id = recovered["turn"]["execution_id"]
        peer = service._bindings._entries[sid].live.peer
        original_call = peer.call
        def lose_answer_ack(method, params, **kwargs):
            result = original_call(method, params, **kwargs)
            if method == "request.answer":
                assert result["status"] == "ok"
                raise ConversationError(Refusal.UNKNOWN)
            return result
        peer.call = lose_answer_ack
        with pytest.raises(ConversationError):
            service.respond(scope, sid, question["id"], {"answer": "Yes"})
        peer.call = original_call
        assert service.respond(scope, sid, question["id"], {"answer": "Yes"}) == {"accepted": True}
        assert provider.partial.wait(10)
        streamed = until(open_, lambda page: page["recovery"].get("inflight_position", {}).get("assistant", 0) > 0)
        position = streamed["recovery"]["inflight_position"]
        assert position["execution_id"] == execution_id
        prefix = service.inflight(scope, sid, {"execution_id": execution_id,
            "field": "assistant", "through": position["assistant"], "offset": 0,
            "revision": position["revision"]})
        assert prefix["text"].strip() == "Recovered prefix 🌍"
        first = service.stop(scope, sid, "original")
        second = service.stop(scope, sid, "original")
        assert first["cancel_requested"] and second["cancel_requested"]
        assert second["execution_id"] == execution_id
        provider.release.set()
        settled = until(lambda: service.read(scope, sid, 0, "original"),
                        lambda page: page["turn"]["state"] not in {"dispatching", "running", "unknown"})
        assert settled["turn"]["state"] == "stopped"
        assert len(provider.requests) == 2, "reconstruction must not execute another prompt"
    finally:
        provider.release.set()
        service.close()
        provider.close()
