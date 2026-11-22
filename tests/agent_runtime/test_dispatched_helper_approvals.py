"""A helper a lead dispatches answers its approvals under the LEAD's policy, never its own 60 s window.

Row ``RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS`` (owner 2026-11-22: "1 a / 2 keep"):
the lead's Smart reviewer or the person in the lead's chat answers, an Off lead's helper runs Off, the
hard blocks hold whatever the mode, a person-wait has no expiry and is not budget spent, and a Stop still
ends it. Real upstream approval queue (``tools.approval``) under the fork's ``session_approval_scope``.

Homes: the lead persona binds no profile, so its policy is read on the head home (``HERMES_HEAD_HOME``,
``approvals.mode: off``, deny ``lead-forbidden*``); the helper's turn runs on its own profile home
(``approvals.mode: manual``, ``timeout: 0``, deny ``helper-forbidden*``) — without the lead's policy every
flagged step of the helper times out at once, which is the 60 s expiry the row saw, made instant.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agent_runtime import live_turns, mission_chat_door
from agent_runtime.profile_context import process_home_scope
from agent_runtime.serde import safe_assignment_token
from agent_runtime.session_control_store import SessionControlStore
from agent_runtime.session_controls import (
    APPROVAL_CHOICES,
    dispatched_person_wait_seconds,
    pending_session_approvals,
    session_approval_scope,
    turn_approval_policy,
)
from tests.agent_runtime.test_operator_session_inspection import target
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, placed_agent, qa_persona  # noqa: F401
from tests.waiting import wait_until

HELPER = "persona_chat_dispatched_helper_root"
RISKY_PROBE = "git reset --hard"


def _config(home, approvals: dict) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"approvals": approvals}), encoding="utf-8")


@pytest.fixture
def lead(placed_agent, tmp_path, monkeypatch):
    from hermes_constants import get_hermes_home

    head = get_hermes_home()
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))
    _config(head, {"mode": "off", "timeout": 0, "deny": ["lead-forbidden*"]})
    helper_home = tmp_path / "helper-profile-home"
    _config(helper_home, {"mode": "manual", "timeout": 0, "deny": ["helper-forbidden*"]})
    chat = target(placed_agent["persona_instance_id"])
    yield SimpleNamespace(root=chat["session_id"], helper_home=helper_home)
    from tools.approval import clear_session, unregister_gateway_notify

    for key in (HELPER, "persona_chat_helpers_helper"):
        clear_session(key)
        unregister_gateway_notify(key)


def _helper_step(lead, command, *, requested_by=None, root=HELPER, turn_key=None, seen=None):
    """One flagged step of a dispatched helper's turn: its profile home, its chat root, its lead."""
    from tools.approval import check_all_command_guards

    if seen is not None:
        seen["thread"] = threading.get_ident()
    with process_home_scope(lead.helper_home), session_approval_scope(
            root, requested_by_session=lead.root if requested_by is None else requested_by, turn_key=turn_key):
        return check_all_command_guards(command, "local")


def _waiting_card(root=HELPER):
    return wait_until(lambda: pending_session_approvals(root), what="the helper's approval card")[0]


def _answer(card, choice, root=HELPER):
    from tools.approval import resolve_gateway_approval

    assert resolve_gateway_approval(root, choice, request_id=card["id"]) == 1


def test_a_smart_leads_helper_runs_a_probe_its_reviewer_approves_with_no_card(lead, monkeypatch):
    """Killing mutations: ``turn_approval_policy`` ignores ``requested_by_session`` -> the helper runs its
    own manual policy and its probe times out unanswered (red: not approved); upstream ``_smart_gate``
    keeps a session approval on APPROVE -> the second probe skips the reviewer (red)."""
    from tools import approval_smart

    SessionControlStore().update(lead.root, "approval_mode", "smart")
    reviewed = []
    monkeypatch.setattr(approval_smart, "_smart_approve", lambda command, description: reviewed.append(command) or "approve")

    first = _helper_step(lead, RISKY_PROBE)
    assert first["approved"] is True and first.get("smart_approved") is True
    assert pending_session_approvals(HELPER) == []
    # Once, for that one command, nothing kept: the same command flagged again is reviewed again.
    second = _helper_step(lead, RISKY_PROBE)
    assert second["approved"] is True
    assert reviewed == [RISKY_PROBE, RISKY_PROBE]


def test_a_manual_leads_helper_card_waits_past_the_helpers_window_until_answered(lead):
    """Killing mutation: ``wait_without_expiry=False`` in ``session_approval_scope`` -> the helper's own
    ``timeout: 0`` ends the wait at once (red: the future is done before the answer)."""
    SessionControlStore().update(lead.root, "approval_mode", "manual")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_helper_step, lead, RISKY_PROBE)
        card = _waiting_card()
        time.sleep(1.5)  # past the helper's window (0 s) and the lead profile's (0 s)
        assert not future.done()
        assert card["command"] == RISKY_PROBE
        _answer(card, "once")
        result = future.result(timeout=10)
    assert result["approved"] is True


def test_a_helper_answers_once_or_deny_never_a_standing_approval(lead):
    """No agent and no card answer picks a session/always approval for a helper. Killing mutation: add
    ``"session"`` to ``APPROVAL_CHOICES`` -> the console accepts a standing answer (red)."""
    from agent_runtime.operator_session_controls import OperatorConversationRefused, respond_operator_approval

    SessionControlStore().update(lead.root, "approval_mode", "manual")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_helper_step, lead, RISKY_PROBE)
        card = _waiting_card()
        try:
            assert {row["id"] for row in card["choices"]} == {"once", "deny"}
            for standing in ("session", "always"):
                with pytest.raises(OperatorConversationRefused):
                    respond_operator_approval({"approval_id": card["id"], "choice": standing, "session_id": HELPER})
            assert not future.done()
        finally:
            if not future.done():
                _answer(card, "deny")
        assert future.result(timeout=10)["approved"] is False
    assert APPROVAL_CHOICES == ("once", "deny")


def test_a_turn_from_a_chat_this_install_does_not_hold_keeps_the_helpers_own_policy(lead):
    """A cross-install turn names no chat of this install (a peer turn carries none at all), so the helper
    keeps its own policy. Killing mutation: ``_lead_policy`` stops refusing an owner it cannot find and
    reads the head profile's ``off`` -> the probe runs (red)."""
    from agent_runtime.chat_turn import normalize_peer_chat_execute

    foreign = "persona_chat_on_another_install"
    policy = turn_approval_policy(HELPER, requested_by_session=foreign)
    assert policy.dispatched is False and policy.mode == "off"  # this test's own home reads ``off``
    result = _helper_step(lead, RISKY_PROBE, requested_by=foreign)
    assert result["approved"] is False and result["outcome"] == "timeout"
    peer = normalize_peer_chat_execute(
        {"turn_request_id": "peer-1", "target": "dev", "message": "hi", "max_seconds": 30,
         "approval_mode": "off", "requested_by_session": lead.root},
        peer_install_id="install-b")
    assert "--requested-by-session" not in peer.argv and "off" not in peer.argv


def test_an_off_leads_helper_runs_off_and_the_hard_blocks_still_hold(lead):
    """Owner "2 keep". The lead chat saves no mode, so its PROFILE's ``off`` governs. Killing mutation:
    drop ``also_deny=policy.lead_deny`` in ``session_approval_scope`` -> the lead's deny glob no longer
    blocks (red)."""
    policy = turn_approval_policy(HELPER, requested_by_session=lead.root)
    assert policy.mode == "off" and policy.dispatched and policy.lead_deny == ("lead-forbidden*",)
    assert _helper_step(lead, RISKY_PROBE)["approved"] is True
    hardline = _helper_step(lead, "rm -rf /")
    assert hardline["approved"] is False and hardline.get("hardline") is True
    assert _helper_step(lead, "echo hunter2 | sudo -S ls /root")["approved"] is False
    for denied in ("lead-forbidden now", "helper-forbidden now"):
        verdict = _helper_step(lead, denied)
        assert verdict["approved"] is False and verdict.get("user_deny") is True, denied
    assert pending_session_approvals(HELPER) == []


@pytest.mark.parametrize("verdict", ["escalate", "deny"])
def test_a_smart_escalate_and_an_overridable_deny_wait_for_a_person(lead, monkeypatch, verdict):
    """Killing mutation: ``wait_without_expiry=False`` -> the card expires at the helper's 0 s (red)."""
    from tools import approval_smart
    from tools.approval import is_approved, list_gateway_approvals

    SessionControlStore().update(lead.root, "approval_mode", "smart")
    monkeypatch.setattr(approval_smart, "_smart_approve", lambda command, description: verdict)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_helper_step, lead, RISKY_PROBE)
        card = _waiting_card()
        raw = list_gateway_approvals(HELPER)[0]
        if verdict == "deny":
            assert raw.get("smart_denied") is True and raw["allow_session"] is False
        time.sleep(1.0)
        assert not future.done()
        _answer(card, "once")
        assert future.result(timeout=10)["approved"] is True
    assert not is_approved(HELPER, raw["pattern_key"])


def test_a_helpers_helper_answers_to_the_root_lead(lead):
    """``A -> B -> C``: C follows A. Killing mutation: resolve the requester itself instead of
    ``_dispatch_leads.get(requester, requester)`` -> B, a chat no instance holds, leaves C on its own
    manual policy (red)."""
    middle = "persona_chat_helpers_helper"
    SessionControlStore().update(lead.root, "approval_mode", "off")
    with session_approval_scope(middle, requested_by_session=lead.root):
        pass
    policy = turn_approval_policy(HELPER, requested_by_session=middle)
    assert policy.lead_root == lead.root and policy.mode == "off"
    assert _helper_step(lead, RISKY_PROBE, requested_by=middle)["approved"] is True
    # A person's own turn on B makes B its own root again.
    with session_approval_scope(middle):
        pass
    assert turn_approval_policy(HELPER, requested_by_session=middle).dispatched is False


def test_a_helper_never_supplies_a_sudo_password(lead, monkeypatch):
    """A password request is a person's: a helper's turn never answers one itself. Killing mutation:
    ``should_prompt_for_sudo = True`` in ``_transform_sudo_command`` -> the prompt runs (red)."""
    from tools import terminal_tool_sudo

    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    monkeypatch.delenv("HERMES_INTERACTIVE", raising=False)
    monkeypatch.setattr(terminal_tool_sudo, "_prompt_for_sudo_password",
                        lambda *a, **k: pytest.fail("a helper's turn prompted for a sudo password"))
    with process_home_scope(lead.helper_home), session_approval_scope(HELPER, requested_by_session=lead.root):
        assert terminal_tool_sudo._transform_sudo_command("sudo ls /root") == ("sudo ls /root", None)


def _door_turn(lead, outcome: dict):
    """A dispatched turn through the real door: one flagged step under the lead's policy, interruptible
    through ``live_turns`` as a real turn's agent is."""
    from tools.interrupt import set_interrupt

    def turn(args):
        tid = threading.get_ident()
        agent = SimpleNamespace(interrupt=lambda *a, **k: set_interrupt(True, tid, reason="dispatch_cancel"))
        key = safe_assignment_token(str(args.client_message_id))
        try:
            with live_turns.live_turn(turn_id=key, session_id=HELPER, persona_instance_id="personainst_helper",
                                      agent=agent):
                outcome["verdict"] = _helper_step(lead, RISKY_PROBE, turn_key=args.client_message_id)
        finally:
            set_interrupt(False, tid)
        args.payload_sink({"ok": True, "reply": "done", "session_id": HELPER})
        return 0

    return turn


def _spec(max_seconds: float) -> dict:
    return {"persona_id": "dev", "message": "probe the tree", "max_seconds": max_seconds,
            "client_message_id": "dispatch-helperappr-1", "requested_by": "agent:lead"}


def test_a_manual_leads_helper_waits_past_its_budget_then_runs(lead, monkeypatch):
    """Killing mutation: drop ``+ _person_wait(args)`` in ``native.run_turn`` -> the supervisor calls
    the wait ``budget_exceeded`` and interrupts it (red: denied, exit_reason set)."""
    from tools.agent_chat_dispatch import native

    SessionControlStore().update(lead.root, "approval_mode", "manual")
    monkeypatch.setattr(native, "KILL_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(native, "SUPERVISE_POLL_SECONDS", 0.02)
    monkeypatch.setattr(native, "ABANDON_GRACE_SECONDS", 0.5)
    outcome: dict = {}
    monkeypatch.setattr(mission_chat_door, "_turn", _door_turn(lead, outcome))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(native.run_turn, _spec(1.0), budget=1.0, stop_requested=lambda: False)
        card = _waiting_card()
        try:
            time.sleep(2.5)  # past the budget and its grace, twice over
            waited = dispatched_person_wait_seconds("dispatch-helperappr-1")
            assert not future.done(), future.result()
            assert waited >= 1.5, waited
        finally:
            _answer(card, "once")
        run = future.result(timeout=10)
    assert run.exit_reason == "" and not run.abandoned
    assert outcome["verdict"]["approved"] is True


def test_stop_ends_a_waiting_helper(lead, monkeypatch):
    """A Stop in Running now still ends a helper parked on a card with no expiry, fail-closed. Killing
    mutation: drop the ``is_interrupted()`` arm of upstream ``_poll_event`` -> the wait never ends (red)."""
    from tools.agent_chat_dispatch import native

    SessionControlStore().update(lead.root, "approval_mode", "manual")
    monkeypatch.setattr(native, "SUPERVISE_POLL_SECONDS", 0.02)
    monkeypatch.setattr(native, "ABANDON_GRACE_SECONDS", 5.0)
    stop = threading.Event()
    outcome: dict = {}
    monkeypatch.setattr(mission_chat_door, "_turn", _door_turn(lead, outcome))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(native.run_turn, _spec(600), budget=600, stop_requested=stop.is_set)
        _waiting_card()
        stop.set()
        run = future.result(timeout=10)
    assert run.interrupted and not run.abandoned
    assert outcome["verdict"]["approved"] is False and outcome["verdict"]["outcome"] == "cancelled"
    assert pending_session_approvals(HELPER) == []


def test_the_turns_hard_wall_waits_out_a_person_wait(lead, monkeypatch):
    """The turn's own wall (``OperatorTurn.start_wall_timers``) re-arms for a dispatched turn's
    person-wait. Killing mutation: fire the wall in ``wall_timer_fired`` regardless of ``waited`` (red:
    the budget trips while the person is still answering)."""
    from threading import Event

    from agent_runtime.operator_turn_policy import OperatorTurn
    from tools.approval_human_wait import human_wait_window

    turn = OperatorTurn.__new__(OperatorTurn)
    turn.request = SimpleNamespace(client_message_id="wall-turn-1")
    turn._wall_closed = False
    tripped = Event()
    monkeypatch.setattr(turn, "interrupt_for_budget", lambda seconds, expired: tripped.set(), raising=False)
    waiting, done = Event(), Event()

    def person_wait():
        with human_wait_window(HELPER):
            waiting.set()
            done.wait(5)

    with process_home_scope(lead.helper_home), session_approval_scope(
            HELPER, requested_by_session=lead.root, turn_key="wall-turn-1"):
        worker = threading.Thread(target=person_wait, daemon=True)
        worker.start()
        assert waiting.wait(5)
        time.sleep(0.4)
        timers: list = []
        turn.wall_timer_fired(1.0, Event(), timers, 0.0)
        assert not tripped.is_set() and len(timers) == 1
        time.sleep(0.6)
        assert not tripped.is_set()  # still waiting: each re-arm credits the wait so far
        done.set()
        worker.join(5)
        assert tripped.wait(5)  # the wait ended, the wall fires
    for timer in timers:
        timer.cancel()


def test_the_lead_folds_never_touch_the_cached_config(lead):
    """The fold is a read view: the next turn of this profile reads its own window and deny list.
    Killing mutation: fold the live section in place in ``project_readonly_config`` (no ``dict(current)``)
    -> the no-expiry window and the lead's glob outlive the turn (red)."""
    from hermes_cli.config import load_config_readonly

    with process_home_scope(lead.helper_home):
        with session_approval_scope(HELPER, requested_by_session=lead.root):
            folded = load_config_readonly()["approvals"]
            assert folded["timeout"] > 86400 and folded["deny"] == ["helper-forbidden*", "lead-forbidden*"]
        after = load_config_readonly()["approvals"]
    assert after["timeout"] == 0 and after["deny"] == ["helper-forbidden*"]
