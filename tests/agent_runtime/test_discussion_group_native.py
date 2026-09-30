"""Real profile workers and RPC producers against a loopback-only model."""
import threading
from http.server import ThreadingHTTPServer

import pytest

from agent_runtime.conversations.service import ConversationService
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.service import DiscussionService
from tests.agent_runtime.native_recovery_provider import until
from tests.agent_runtime.test_native_conversation_roundtrip import Provider
from tests.agent_runtime.test_discussion_profile_groups import create, act, idle
from tests.agent_runtime.test_discussion_member_models import model_call

pytestmark = pytest.mark.timeout(180)


def test_real_group_compare_discuss_target_and_reopen(tmp_path):
    Provider.requests = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    for name in ("runtime", "home", "a", "b", "work"):
        (tmp_path / name).mkdir()
    owner = tmp_path / "home"
    (owner / "config.yaml").write_text(
        f"providers:\n  local-test:\n    api: http://127.0.0.1:{provider.server_port}/v1\n"
        "    key_env: PRIVATE_LLM_KEY\n    models: [test-model]\n    discover_models: false\n", encoding="utf-8")
    (owner / ".env").write_text("PRIVATE_LLM_KEY=isolated-group\n", encoding="utf-8")
    for profile in ("a", "b"):
        (tmp_path / profile / "config.yaml").write_text(
            ("model:\n  default: test-model\n  provider: custom:local-test\n" if profile == "a" else "") +
            "dashboard:\n  turn_isolation: false\nmcp_servers: {}\n", encoding="utf-8")
    root = tmp_path / "runtime"
    conversations = ConversationService(root, "install", profile_home=lambda p: tmp_path / p, auth_home=owner)
    context = NativeContext(root, owner, "install")
    service = DiscussionService(context, active_poll_interval=.05, conversations=lambda: conversations)
    service.start()
    try:
        run = create((service, conversations, None, tmp_path))
        member_b = service.runs.members(run["run_id"])[1]
        facts = model_call(service, run, member_b)
        assert facts["model_selection_required"]
        assert any(m["id"] == '["custom:local-test","test-model"]' for m in facts["models"])
        selected = model_call(service, run, member_b, model_id='["custom:local-test","test-model"]')
        assert not selected["model_selection_required"]
        assert selected["session_id"] == member_b["session_id"]
        assert not Provider.requests
        act(service, run, "send", "compare", message="Give an independent idea",
            response={"mode": "compare", "members": []})
        view = until(lambda: idle(service, run, 1), bool, timeout=60)
        replies = [e for e in view["log"]["events"] if e["kind"] == "message.member"]
        assert len(replies) == 2, view
        assert all(e["payload"]["text"] == "Local native answer" for e in replies)
        act(service, run, "send", "discuss", message="Develop those ideas together")
        until(lambda: idle(service, run, 2), bool, timeout=60)
        member = view["members"][0]["member_id"]
        act(service, run, "send", "reply", message="Explain your idea", response={"mode": "reply", "members": [member]})
        before = until(lambda: idle(service, run, 3), bool, timeout=60)
        assert len([e for e in before["log"]["events"] if e["kind"] == "message.member"]) == 5
        service.close()
        conversations.close()
        requests = len(Provider.requests)
        conversations = ConversationService(root, "install", profile_home=lambda p: tmp_path / p, auth_home=owner)
        service = DiscussionService(context, active_poll_interval=.05, conversations=lambda: conversations)
        service.start()
        after = service.view(run["workspace_id"], run["run_id"])
        assert after["log"]["events"] == before["log"]["events"]
        assert len(Provider.requests) == requests
        assert all(auth == "Bearer isolated-group" for auth, _ in Provider.requests)
        assert not (tmp_path / "b" / "auth.json").exists()
    finally:
        service.close()
        conversations.close()
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=3)
