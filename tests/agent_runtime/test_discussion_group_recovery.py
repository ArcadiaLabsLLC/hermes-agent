"""Group reconstruction preserves native execution and request authority."""
import pytest

from agent_runtime.conversations.model import ConversationError, Refusal
from agent_runtime.discussions.definitions import DefinitionError
from agent_runtime.discussions.profile_groups import ProfileGroupSpec
from agent_runtime.discussions.service import DiscussionService
from tests.agent_runtime.test_discussion_profile_groups import groups as groups, create, act, sends, complete, idle
from tests.agent_runtime.test_discussion_runtime import wait_until

pytestmark = pytest.mark.timeout(90)


@pytest.mark.parametrize("waiting", [False, True])
def test_reconstructs_same_turn_and_question_without_resend(groups, waiting):
    service, conversations, factory, _ = groups
    run = create(groups)
    member = service.runs.members(run["run_id"])[0]["member_id"]
    act(service, run, "send", "request", message="Review", response={"mode": "reply", "members": [member]})
    wait_until(lambda: len(sends(factory)) == 1)
    worker, sent = sends(factory)[0]
    if waiting:
        worker.question(sent["session_id"], "srq-review", method="clarify",
                        questions=[{"qid": "part", "question": "Which part?", "choices": []}])
    service.close()
    replacement = DiscussionService(service.context, active_poll_interval=.02, conversations=lambda: conversations)
    replacement.start()
    try:
        view = replacement.view(run["workspace_id"], run["run_id"])
        task = view["tasks"][0]
        if waiting:
            assert task["question"]["request"]["id"] == "srq-review"
            act(replacement, run, "respond", "answer", task_id=task["task_id"], generation=task["generation"],
                native_id=task["native_id"], request_id="srq-review", result={"answers": {"part": "Architecture"}})
            assert len(worker.answers) == 1
        act(replacement, run, "stop", "stop")
        wait_until(lambda: worker.executions[sent["session_id"]]["cancel_requested"])
        assert replacement.runs.get(run["run_id"])["phase"] == "stopping"
        complete(factory, status="interrupted")
        wait_until(lambda: replacement.runs.get(run["run_id"])["phase"] == "paused")
        assert len(sends(factory)) == 1
    finally:
        replacement.close()


def test_lost_submission_ack_uses_same_native_receipt(groups, monkeypatch):
    service, conversations, factory, _ = groups
    run = create(groups)
    original = conversations.send

    def lose_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise ConversationError(Refusal.UNKNOWN)

    monkeypatch.setattr(conversations, "send", lose_ack)
    act(service, run, "send", "compare", message="Review", response={"mode": "compare", "members": []})
    wait_until(lambda: len(sends(factory)) == 2)
    complete(factory)
    wait_until(lambda: idle(service, run, 1))
    assert len(sends(factory)) == 2


def test_crash_before_native_route_admission_is_not_a_permanent_unknown(groups):
    service, _, factory, _ = groups
    run = create(groups)
    member = service.runs.members(run["run_id"])[0]
    attempt = service.attempts.begin(run["run_id"], "unsubmitted", 1, member, "Never sent")
    service.attempts.claim(attempt, pid=123, started=123)
    recovered = service.executions.profiles.turns.recover(attempt)
    assert recovered["stage"] == "terminal"
    assert recovered["receipt"]["error"] == "dispatch_not_admitted"
    assert not factory.workers


def test_duplicate_profile_cannot_manufacture_two_members_by_changing_home(groups):
    service, _, _, root = groups
    run = create(groups)
    spec = service.runs.get(run["run_id"])["initial"]["group"]
    value = {k: spec[k] for k in ("name", "participants", "cwd")}
    value["participants"][1]["profile"] = "a"
    with pytest.raises(DefinitionError, match="duplicate_participant"):
        ProfileGroupSpec.parse(value)
