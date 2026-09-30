"""Group questions and Stop cross the real compute-host acknowledgement boundary."""
import pytest

from agent_runtime.conversations.model import ConversationError, Refusal
from agent_runtime.conversations.service import ConversationService
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.service import DiscussionService
from tests.agent_runtime.native_recovery_provider import RecoveryProvider, until
from tests.agent_runtime.test_discussion_profile_groups import create, act

pytestmark = pytest.mark.timeout(120)


def test_compute_question_lost_answer_ack_and_confirmed_stop(tmp_path, monkeypatch):
    for name in ("runtime", "home", "a", "b", "work"):
        (tmp_path / name).mkdir()
    provider = RecoveryProvider()
    provider.configure(tmp_path / "a", compute=True)
    conversations = ConversationService(tmp_path / "runtime", "install", profile_home=lambda p: tmp_path / p)
    context = NativeContext(tmp_path / "runtime", tmp_path / "home", "install")
    service = DiscussionService(context, active_poll_interval=.05, conversations=lambda: conversations)
    service.start()
    try:
        run = create((service, conversations, None, tmp_path))
        member = service.runs.members(run["run_id"])[0]["member_id"]
        act(service, run, "send", "question", message="Ask whether to continue.",
            response={"mode": "reply", "members": [member]})
        def view():
            return service.view(run["workspace_id"], run["run_id"])
        asked = until(view, lambda v: any(t["question"] for t in v["tasks"]))
        task = next(t for t in asked["tasks"] if t["question"])
        question = task["question"]["request"]
        answer = {"task_id": task["task_id"], "generation": task["generation"], "native_id": task["native_id"],
            "request_id": question["id"], "result": {"answers": {question["params"]["questions"][0]["qid"]: "Yes"}}}
        original = conversations.respond
        def lose_ack(*args, **kwargs):
            original(*args, **kwargs)
            raise ConversationError(Refusal.UNKNOWN)
        monkeypatch.setattr(conversations, "respond", lose_ack)
        with pytest.raises(ConversationError):
            act(service, run, "respond", "answer", **answer)
        monkeypatch.setattr(conversations, "respond", original)
        act(service, run, "respond", "answer", **answer)
        assert provider.partial.wait(10)
        original_stop = conversations.stop
        def lose_stop_ack(*args, **kwargs):
            original_stop(*args, **kwargs)
            raise ConversationError(Refusal.UNKNOWN)
        monkeypatch.setattr(conversations, "stop", lose_stop_ack)
        act(service, run, "stop", "stop")
        monkeypatch.setattr(conversations, "stop", original_stop)
        act(service, run, "stop", "stop")
        # Compute can confirm interruption before this read; never require a timed intermediate state.
        assert service.runs.get(run["run_id"])["phase"] in {"stopping", "paused"}
        provider.release.set()
        stopped = until(view, lambda v: v["run"]["phase"] == "paused")
        assert stopped["tasks"][0]["status"] == "cancelled"
        assert len(provider.requests) == 2
    finally:
        provider.release.set()
        service.close()
        conversations.close()
        provider.close()
