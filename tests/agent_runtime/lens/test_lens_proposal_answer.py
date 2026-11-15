"""You approve or deny what Lens proposes; an unanswered proposal expires after a day (row
``RT-LENS-PROPOSAL-APPROVE-DENY``, design ``planned/lens-act-and-safe-investigate.md`` §4, decision 5).

The act harness (``test_lens_act.py``): the turns' tool calls go through the real eternia-harness hooks.

Gates and their killing mutations (each red recorded in the row's commit):

* an approval forges ONE follow-up turn in the Episode's own chat, where the approved call runs (decided by
  the owner) — killed by dropping ``self._proposals`` from ``tick`` (no second turn) and by dropping the
  ``preadmitted`` arm in ``ActTurn.decide`` (the call is proposed again);
* the pre-admission is one-shot: the same call a second time is judged afresh — killed by not clearing
  ``self.preadmitted``;
* the follow-up runs once — killed by dropping both ``follow_up_turn_id IS NULL`` guards in
  ``claim_follow_ups`` (the select and the claiming update; either alone holds);
* a denial forges nothing; an answer is given once — killed by dropping both the ``result != PROPOSED``
  check and the update's ``result = ?`` guard in ``answer_proposal`` (either alone holds); an answer past
  the 24 h is refused before any tick — killed by dropping the TTL test there;
* an unanswered proposal expires after 24 h and can no longer be answered — killed by dropping
  ``expire_proposals`` from ``_proposals``;
* the follow-up's tokens add to the Episode's — killed by dropping ``add_spend``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from test_lens_act import _act, _actions, hooks  # noqa: F401  (hooks: fixture)
from test_lens_exit_door import T0, _armed, _episode, _rpc, door  # noqa: F401  (door: fixture)

from agent_runtime.lens.trigger import LensForge

RESTART = {"command": "systemctl restart api"}


@pytest.fixture(autouse=True)
def _owner_clock(monkeypatch):
    """The owner answers an hour after the door's clock (T0): inside the proposal's day."""

    from agent_runtime.lens import store_actions
    from agent_runtime.lens.store import to_ms

    monkeypatch.setattr(store_actions, "wall_ms", lambda: to_ms(T0 + timedelta(hours=1)))


def _script(door, hooks, monkeypatch, *, first, follow_up=()):
    """Inside each turn: the first turn makes ``first`` calls, a follow-up turn ``follow_up``; refusals kept."""

    seen = {"first": [], "follow_up": []}

    def during(args):
        import agent_runtime.persona_turn_binding as binding

        agent = type("Agent", (), {"_persona_chat_client_message_id": args.client_message_id})()
        monkeypatch.setattr(binding, "current_persona_turn_agent", lambda: agent)
        which = "follow_up" if ":approved:" in args.client_message_id else "first"
        for i, (tool, tool_args) in enumerate(first if which == "first" else follow_up):
            call_id = f"{which}_{i}"
            verdict = hooks.refuse_tool_call(tool_name=tool, args=tool_args, tool_call_id=call_id)
            seen[which].append(None if verdict is None else verdict["message"])
            if verdict is None:
                hooks.record_turn_outcome(tool_name=tool, args=tool_args, tool_call_id=call_id, status="ok")

    door.during = during
    return seen


def _forge(at=T0):
    return LensForge(clock=lambda: at)


def _proposal() -> dict:
    return next(a for a in _actions() if a["result"] in ("proposed", "approved", "denied", "expired"))


def test_an_approval_runs_the_call_once_in_a_follow_up_turn_of_the_same_chat(door, hooks, monkeypatch, guardian):
    store = _armed(_act(("write_file",)))  # terminal is not listed: a proposal
    seen = _script(door, hooks, monkeypatch, first=[("terminal", RESTART)],
                   follow_up=[("terminal", RESTART), ("terminal", RESTART)])
    assert _forge().tick() == ["forged"]
    proposal = _proposal()
    assert (proposal["result"], proposal["expires_ms"]) == ("proposed", proposal["created_ms"] + 86_400_000)

    answered = _rpc("runtime.lens.proposal.answer", {"action_id": proposal["action_id"], "decision": "approve"})
    assert answered["result"]["result"] == "approved" and answered["result"]["expires_ms"] is None

    assert _forge().tick() == ["follow_up_forged"]
    first, follow = door.calls
    assert follow.session_id == first.session_id and len(door.opener.calls) == 1  # the Episode's own chat
    assert follow.client_message_id == f"{first.client_message_id}:approved:{proposal['action_id']}"
    assert "[LENS APPROVED ACTION" in follow.message and "systemctl restart api" in follow.message
    assert seen["follow_up"][0] is None and seen["follow_up"][1].startswith("Sent to the owner")  # one-shot
    rows = _actions()
    ran = [a for a in rows if a["result"] == "ran"]
    assert [(a["tool"], a["decided_by"], a["why"], a["verdict"]) for a in ran] == [
        ("terminal", "owner", "owner_approved", None)]
    assert _proposal()["follow_up_turn_id"] == follow.client_message_id
    assert _forge().tick() == [] and len(door.calls) == 2  # never forged twice
    assert store.receipt(_episode(1).id)["budget"]["tokens_used"] == 212  # the investigate check; fake turns spend 0


def test_a_follow_ups_spend_adds_to_the_episodes(door, hooks, monkeypatch, guardian):
    import agent_runtime.turn_token_budget as ttb

    store = _armed(_act(("write_file",)))
    _script(door, hooks, monkeypatch, first=[("terminal", RESTART)])
    _forge().tick()
    _rpc("runtime.lens.proposal.answer", {"action_id": _proposal()["action_id"], "decision": "approve"})
    original = ttb.TurnTokenBudget.summary  # the follow-up turn spends 500 tokens
    monkeypatch.setattr(ttb.TurnTokenBudget, "summary",
                        lambda self: {**original(self), "tokens_used": self.tokens + 500, "calls_used": self.calls + 2})
    assert _forge().tick() == ["follow_up_forged"]

    assert store.receipt(_episode(1).id)["budget"]["tokens_used"] == 212 + 500


def test_a_denial_runs_nothing_and_an_answer_is_given_once(door, hooks, monkeypatch, guardian):
    _armed(_act(("write_file",)))
    _script(door, hooks, monkeypatch, first=[("terminal", RESTART)])
    _forge().tick()
    action_id = _proposal()["action_id"]

    assert _rpc("runtime.lens.proposal.answer", {"action_id": action_id, "decision": "deny"})["result"]["result"] == (
        "denied")
    again = _rpc("runtime.lens.proposal.answer", {"action_id": action_id, "decision": "approve"})["error"]
    assert again["data"]["reason"] == "proposal_settled"
    assert _forge().tick() == [] and len(door.calls) == 1


def test_an_unanswered_proposal_expires_after_a_day(door, hooks, monkeypatch, guardian):
    _armed(_act(("write_file",)))
    _script(door, hooks, monkeypatch, first=[("terminal", RESTART)])
    _forge().tick()

    assert _forge(T0 + timedelta(hours=23)).tick() == []
    from agent_runtime.lens import store_actions
    from agent_runtime.lens.store import to_ms

    monkeypatch.setattr(store_actions, "wall_ms", lambda: to_ms(T0 + timedelta(hours=25)))  # before any tick
    late = _rpc("runtime.lens.proposal.answer", {"action_id": _proposal()["action_id"], "decision": "approve"})
    assert late["error"]["data"]["reason"] == "proposal_settled"
    assert _forge(T0 + timedelta(hours=24)).tick() == ["proposal_expired"]

    proposal = _proposal()
    assert (proposal["result"], proposal["expires_ms"]) == ("expired", None)
    late = _rpc("runtime.lens.proposal.answer", {"action_id": proposal["action_id"], "decision": "approve"})
    assert late["error"]["data"]["reason"] == "proposal_settled"


def test_only_a_proposal_can_be_answered(door, hooks, monkeypatch, guardian):
    _armed(_act(("write_file",)))
    _script(door, hooks, monkeypatch, first=[("write_file", {"path": "x"})])  # approved by the rules, ran
    _forge().tick()
    [ran] = _actions()

    for action_id in (ran["action_id"], "lens-action-unknown"):
        refused = _rpc("runtime.lens.proposal.answer", {"action_id": action_id, "decision": "approve"})["error"]
        assert refused["data"]["reason"] == "proposal_not_found"
    bad = _rpc("runtime.lens.proposal.answer", {"action_id": ran["action_id"], "decision": "maybe"})["error"]
    assert bad["data"]["reason"] == "invalid_value"
