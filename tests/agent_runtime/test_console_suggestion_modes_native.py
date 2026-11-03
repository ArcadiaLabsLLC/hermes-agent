"""The Manual verb through the real authenticated dispatcher and native history owner."""
from tests.waiting import wait_until
from tests.agent_runtime.test_console_suggestions_native import native
from agent_runtime import serve_rpc
from agent_runtime.console_suggestions.service import ConsoleSuggestions


def test_manual_rpc_observation_click_and_owner_fences(native):
    home, target = native
    calls = []
    service = ConsoleSuggestions(home, generator=lambda messages: calls.append(messages) or {"text": "Show the next example.", "usage": {}})
    context = serve_rpc.RpcContext(emit=lambda frame: None, console_suggestions=lambda: service)
    prefix = "runtime.operator.conversation.suggestions"
    def call(method, **extra):
        return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "modes", "method": method, "params": {**target, **extra}}, context)
    try:
        settings = call("runtime.console_suggestions.settings.get")["result"]
        assert settings["mode"] == "off"
        settings = call("runtime.console_suggestions.settings.set", expected_revision=settings["settings_revision"], mode="manual", cooldown_seconds=0)["result"]
        epoch = settings["policy_epoch"]
        assert call(prefix + ".request", expected_policy_epoch=epoch)["error"]["data"]["reason"] == "conversation_not_observed"
        assert call(prefix + ".subscribe")["result"]["state"] == "idle"
        service.changed()
        assert not calls and service.pool is None
        denied = call(prefix + ".request", expected_policy_epoch=epoch, client_scope="b" * 64)
        assert denied["error"]["data"]["reason"] == "conversation_owner_changed"
        assert call(prefix + ".request", expected_policy_epoch=epoch)["result"]["accepted"]
        wait_until(lambda: not service.pending and not service.running, timeout=5)
        assert call(prefix + ".read")["result"]["text"] == "Show the next example."
        assert len(calls) == 1
    finally:
        service.close()
