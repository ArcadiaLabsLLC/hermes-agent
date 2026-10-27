"""RT-SKILL-CHANGE-RECORD — a background-review skill change names the chat and turn it came from.

The review fork changes a skill after the turn, so the record is keyed by what the turn bound
(``persona_turn_binding.current_turn_origin``, copied into the review thread's context), joined to
upstream's skill ledger entry the call appended; ``runtime.skills.changes.list`` reads a skill's
history with diffs, or one turn's changes, and the staged writes with their turn and status.
"""

from __future__ import annotations

import contextvars
import json
from types import SimpleNamespace

import pytest

from agent_runtime import review_skill_changes as changes
from agent_runtime.persona_turn_binding import bind_persona_turn_agent, current_turn_origin
from agent_runtime.profile_context import process_home_scope
from agent_runtime.review_skill_pending import list_staged, reject_staged
from agent_runtime.serve_rpc import skills_pending as rpc
from tools.skill_provenance import BACKGROUND_REVIEW, reset_current_write_origin, set_current_write_origin

TURN = {"chat_session_id": "chat-root-1", "turn_id": "agent-chat-send-1"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "_default_hermes_root_memo", None, raising=False)
    return root


def _agent(**turn):
    return SimpleNamespace(_persona_chat_root_session_id=turn.get("chat_session_id"),
                           _persona_chat_turn_id=turn.get("turn_id"))


def _patch_skill(home, before: str, after: str, *, session_id: str = "native-1") -> None:
    """The mutation ``skill_manage`` makes, with upstream's own ledger capture around it."""
    from tools import skill_ledger

    package = home / "skills" / "git"
    package.mkdir(parents=True, exist_ok=True)
    (package / "SKILL.md").write_text(before, encoding="utf-8")
    captured = skill_ledger.capture_before(package)
    (package / "SKILL.md").write_text(after, encoding="utf-8")
    skill_ledger.record_mutation("patch", "git", before=captured, after_root=package,
                                 evidence={"session_id": session_id})


def _review_call(home, *, review: bool = True) -> None:
    token = set_current_write_origin(BACKGROUND_REVIEW if review else "foreground")
    try:
        _patch_skill(home, "# Git\nold step\n", "# Git\nnew step\n")
        changes.on_post_tool_call(tool_name="skill_manage", args={"action": "patch", "name": "git"},
                                  result=json.dumps({"success": True}), session_id="native-1", duration_ms=40)
    finally:
        reset_current_write_origin(token)


def test_the_turn_is_copied_at_bind_so_a_later_turn_cannot_relabel_the_review():
    agent = _agent(**TURN)
    with bind_persona_turn_agent(agent):
        review_context = contextvars.copy_context()  # what the review thread is started with
        agent._persona_chat_turn_id = "agent-chat-send-2"  # the next turn on the same agent
    assert review_context.run(current_turn_origin) == TURN
    assert current_turn_origin() is None


def test_a_review_change_lists_with_its_turn_and_diff(home):
    with bind_persona_turn_agent(_agent(**TURN)):
        _review_call(home)
    history = changes.list_changes(skill="git")
    [row] = history["changes"]
    assert (row["skill"], row["action"], row["review"], row["turn"]) == ("git", "patch", True, TURN)
    assert "-old step" in row["diff"] and "+new step" in row["diff"] and row["files"] == ["git/SKILL.md"]
    assert [r["entry_id"] for r in changes.list_changes(turn_id=TURN["turn_id"])["changes"]] == [row["entry_id"]]
    assert changes.list_changes(chat_session_id="chat-root-1")["changes"][0]["turn"] == TURN
    assert changes.list_changes(turn_id="agent-chat-send-other")["changes"] == []


def test_a_foreground_write_is_history_but_no_review_change(home):
    """Positive control: the same write without the review origin is in the skill's history, unattributed."""
    with bind_persona_turn_agent(_agent(**TURN)):
        _review_call(home, review=False)
    [row] = changes.list_changes(skill="git")["changes"]
    assert row["review"] is False and row["turn"] is None
    assert changes.list_changes(turn_id=TURN["turn_id"])["changes"] == []


def test_a_review_outside_a_bound_turn_records_no_turn(home):
    _review_call(home)
    [row] = changes.list_changes(skill="git")["changes"]
    assert row["review"] is True and row["turn"] is None


def test_a_staged_write_carries_its_turn_and_status(home):
    from tools import write_approval as wa

    with process_home_scope(home):
        record = wa.stage_write(wa.SKILLS, {"action": "patch", "name": "git", "old_string": "a", "new_string": "b"},
                                summary="[shared] demo", origin="background_review")
        with bind_persona_turn_agent(_agent(**TURN)):
            changes.record_staged(record["id"], ["git"], "patch")
    [pending] = list_staged()["pending"]
    assert pending["origin"] == "background_review" and pending["turn"] == TURN
    [staged] = changes.list_changes(turn_id=TURN["turn_id"])["staged"]
    assert (staged["pending_id"], staged["status"], staged["turn"]) == (record["id"], "pending", TURN)
    reject_staged(profile="default", pending_id=record["id"])
    assert changes.list_changes(skill="git")["staged"][0]["status"] == "rejected"


def test_the_method_lane_reads_and_refuses_typed(home):
    with bind_persona_turn_agent(_agent(**TURN)):
        _review_call(home)
    answer = rpc._runtime_skills_changes_list(1, {"skill": "git", "limit": 5})
    assert answer["result"]["changes"][0]["turn"] == TURN, answer
    assert rpc._runtime_skills_changes_list(1, {"limit": 0})["error"]["data"]["reason"] == "invalid_params"
    assert rpc._runtime_skills_changes_list(1, {"skill": 3})["error"]["data"]["reason"] == "invalid_params"
    assert rpc._runtime_skills_changes_list(1, {"profile": "nobody"})["error"]["data"]["reason"] == "unknown_profile"


# ── RT-SKILL-CHANGE-EVENT: the change is announced on the stream ─────────────


@pytest.fixture
def events(home, tmp_path, monkeypatch):
    """The real EventLog under a private store root; returns a reader of its skill events."""
    from agent_runtime.events import EventLog

    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "agent-runtime"))
    return lambda: [event for event in EventLog().tail(50) if event.type == "persona_chat.skill_changed"]


def test_an_applied_review_change_is_announced_with_its_profile_skill_action_and_turn(events):
    with bind_persona_turn_agent(_agent(**TURN)):
        _review_call(changes._changes_path().parent)
    [event] = events()
    assert event.payload == {"profile": "default", "skill": "git", "action": "patch", "change": "applied",
                             "turn": TURN}
    assert (event.session_id, event.turn_id) == (TURN["chat_session_id"], TURN["turn_id"])
    # The announced profile is the one the read takes back.
    assert changes.list_changes(profile=event.payload["profile"], skill="git")["changes"]


def test_a_foreground_write_announces_nothing(events):
    """Positive control for the gate the announce sits behind: same write, no review origin."""
    with bind_persona_turn_agent(_agent(**TURN)):
        _review_call(changes._changes_path().parent, review=False)
    assert events() == []


def test_a_deferred_review_announces_a_null_turn(events):
    _review_call(changes._changes_path().parent)
    [event] = events()
    assert event.payload["turn"] is None and event.session_id is None


def test_a_staged_write_is_announced_with_its_staged_id(events, home):
    from tools import write_approval as wa

    with process_home_scope(home):
        record = wa.stage_write(wa.SKILLS, {"action": "patch", "name": "git", "old_string": "a", "new_string": "b"},
                                summary="[shared] demo", origin="background_review")
        with bind_persona_turn_agent(_agent(**TURN)):
            changes.record_staged(record["id"], ["git"], "patch")
    [event] = events()
    assert event.payload == {"profile": "default", "skill": "git", "action": "patch", "change": "staged",
                             "turn": TURN, "staged_id": record["id"]}
