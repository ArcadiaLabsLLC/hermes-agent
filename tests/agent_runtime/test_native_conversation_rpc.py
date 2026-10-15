from agent_runtime.call_authorization import STDIO_OWNER, UNKNOWN_CALLER
from agent_runtime.conversations import binding
from agent_runtime.execution_identity import execution_identity
from agent_runtime.serve_rpc import handle_request
from agent_runtime.serve_rpc.protocol import RpcContext


def test_native_capabilities_require_console_and_selected_execution_identity(tmp_path):
    service = binding.bind(tmp_path, "install")
    request = {"jsonrpc": "2.0", "id": "r", "method": "runtime.conversation.capabilities", "params": {}}
    try:
        denied = handle_request(request, RpcContext(caller=UNKNOWN_CALLER))
        assert "error" in denied
        owner = RpcContext(caller=STDIO_OWNER)
        good = handle_request({**request, "execution_id": execution_identity()["execution_id"]}, owner)
        assert good["result"]["install_id"] == service.install_id
        assert good["result"]["execution_identity_guard"] is True
        wrong = handle_request({**request, "execution_id": "other-checkout"}, owner)
        assert wrong["error"]["data"]["reason"] == "execution_identity_mismatch"
    finally:
        binding.shutdown(root=tmp_path)
