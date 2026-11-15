"""RT-LENS-INVESTIGATE-TOKEN-BUDGET — investigating stops at a token budget, and every limit is editable.

Design ``docs/agent-runtime-harness/planned/lens-act-and-safe-investigate.md`` §3 (owner RULED
2026-11-14: "the budget limits should be easily editable"). No serve, no model: the turn is the fake
mission-chat handler of ``test_lens_exit_door``; its provider calls are ``usage_ledger.record_usage``
calls made inside the persona-turn binding, exactly where the ``post_api_request`` hook makes them.

Gates and their killing mutations (each red recorded in the commit):

* the ceiling lands the turn while one more working call and the landing reply still fit — killed by
  dropping ``2 *`` from ``_stop_reason`` (no drain after the third call);
* the call limit keeps one call for the landing reply — killed by ``self.calls + 1`` -> ``self.calls``;
* the 80 % nudge is steered once, typed ``token_budget`` — killed by dropping the ``not self.nudged`` guard
  (two nudges);
* every provider call reaches the armed turn — killed by removing the ``on_provider_call`` tap from
  ``usage_ledger.record_usage`` (``forged``, 0 tokens);
* the receipt says ``budget_spent`` and carries what was spent — killed by always writing ``forged``;
* a monitor or all Lens over its daily tokens downgrades the next investigate to a notify — killed by
  dropping ``_over_daily_tokens`` from ``_admission`` (a second turn forges);
* the Episode's ceiling never exceeds what is left today — killed by dropping ``left_monitor`` from the
  ``min`` in ``episode_limits``;
* a limit set over the RPC survives a restart and wins over config, ``null`` clears it, the monitor's wins
  over its workspace's — killed by reading ``_config`` before the stored layers in ``_resolved_limits``;
* the edited Lens-wide turn budget is the one admission reads — killed by restoring
  ``lens_setting("daily_turn_budget")`` in ``trigger._over_budget``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from agent_runtime.lens.store import LensStore, MonitorState
from agent_runtime.turn_token_budget import TurnTokenBudget, armed_turn_budget

from tests.agent_runtime.lens.test_lens_exit_door import T0, _Door, _OpenChat, _episode, _monitor, _rpc


class _Iterations:
    def __init__(self, left: int = 50) -> None:
        self.left = left

    def consume(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        return True


class _Agent:
    def __init__(self, client_message_id: str = "turn-1") -> None:
        self._persona_chat_client_message_id = client_message_id
        self.iteration_budget = _Iterations()
        self.steered: list = []

    def steer(self, notice) -> None:
        self.steered.append(notice)


def _calls(agent: _Agent, *sizes: int) -> None:
    """The turn's provider calls, as the ``post_api_request`` hook reports them."""

    from agent_runtime.persona_turn_binding import bind_persona_turn_agent
    from agent_runtime.usage_ledger import bind_usage_ledger, record_usage

    with bind_usage_ledger(), bind_persona_turn_agent(agent):
        for size in sizes:
            record_usage({"prompt_tokens": size - 10, "output_tokens": 10, "total_tokens": size})


# --- the ceiling ------------------------------------------------------------------


def test_the_turn_lands_while_one_more_call_still_fits_for_the_landing_reply():
    agent, budget = _Agent(), TurnTokenBudget(token_limit=10_000, call_limit=30)
    with armed_turn_budget("turn-1", budget):
        _calls(agent, 1_000, 2_000)  # 3,000 spent; another working call and a landing (2 x 2,000) still fit
        assert budget.stopped_by is None and agent.iteration_budget.left == 50
        _calls(agent, 2_500)  # 5,500 spent; one more working call (+2,500) would leave no room for the landing

    assert budget.stopped_by == "tokens" and agent.iteration_budget.left == 0
    assert agent.steered[-1].notice_code == "token_budget"
    assert budget.summary() == {"tokens_used": 5_500, "token_limit": 10_000, "calls_used": 3, "call_limit": 30,
                                "nudged": True, "stopped_by": "tokens"}


def test_the_call_limit_keeps_one_call_for_the_landing_reply():
    agent, budget = _Agent(), TurnTokenBudget(token_limit=None, call_limit=3)
    with armed_turn_budget("turn-1", budget):
        _calls(agent, 10)
        assert budget.stopped_by is None
        _calls(agent, 10)  # call 2 of 3: the landing reply is call 3
        assert budget.stopped_by == "calls"
        _calls(agent, 10)  # the landing reply itself is counted, and changes nothing
    assert budget.calls == 3 and budget.stopped_by == "calls"


def test_the_eighty_percent_nudge_is_steered_once():
    agent, budget = _Agent(), TurnTokenBudget(token_limit=100_000, call_limit=30)
    with armed_turn_budget("turn-1", budget):
        _calls(agent, *[5_000] * 16, 500)  # 80k (+2 x 5k) < 100k: a nudge, no landing; then a small call

    assert [notice.notice_code for notice in agent.steered] == ["token_budget"]
    assert "write what you have found" in str(agent.steered[0])
    assert budget.stopped_by is None and agent.iteration_budget.left == 50


def test_an_unarmed_turn_and_another_turns_calls_are_not_counted():
    budget = TurnTokenBudget(token_limit=1_000, call_limit=30)
    _calls(_Agent("turn-1"), 5_000)  # not armed yet
    with armed_turn_budget("turn-1", budget):
        _calls(_Agent("turn-2"), 5_000)  # a different turn
    assert budget.calls == 0 and budget.tokens == 0


# --- the exit door ----------------------------------------------------------------


@pytest.fixture
def door():
    from agent_runtime import mission_chat_door

    bound, opener = _Door(), _OpenChat()
    mission_chat_door.bind_mission_chat_turn(bound)
    mission_chat_door.bind_open_chat(opener)
    yield bound
    mission_chat_door.bind_mission_chat_turn(None)
    mission_chat_door.bind_open_chat(None)


def _armed_store(*ordinals: int) -> LensStore:
    store = LensStore()
    manifest = _monitor(cap=8)
    store.create(manifest)
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    for ordinal in ordinals or (1,):
        store.save_episode(_episode(ordinal))
    return store


def _spending(*sizes: int):
    agents = []

    def during(args):
        agent = _Agent(args.client_message_id)
        agents.append(agent)
        _calls(agent, *sizes)

    return during, agents


def _forge(clock=None):
    from agent_runtime.lens.trigger import LensForge

    return LensForge(clock=clock or (lambda: T0))


def test_a_turn_that_spends_its_budget_lands_and_its_receipt_says_so(door):
    store = _armed_store()
    assert _rpc("runtime.lens.budget.set", {"scope": "monitor", "monitor_id": "status",
                                            "limits": {"episode_tokens": 5_000}})["result"]
    door.during, agents = _spending(1_000, 1_500)

    assert _forge().tick() == ["budget_spent"]

    [agent] = agents
    assert agent.iteration_budget.left == 0
    receipt = _rpc("runtime.lens.receipt", {"episode_id": _episode(1).id})["result"]
    assert receipt["outcome"] == "budget_spent"
    # The rules check (conftest's guardian: 212 tokens, one call) is the Episode's first spend.
    assert receipt["budget"] == {"tokens_used": 2_712, "token_limit": 5_000, "calls_used": 3, "call_limit": 30,
                                 "stopped_by": "tokens"}


def test_a_turn_inside_its_budget_is_forged_and_counted(door):
    store = _armed_store()
    door.during, _ = _spending(1_200, 800)

    assert _forge().tick() == ["forged"]

    # Two turn calls plus the rules check (212 tokens, one call; RT-LENS-RULES-CHECK-BEFORE-INVESTIGATE).
    assert store.receipt(_episode(1).id)["budget"] == {"tokens_used": 2_212, "token_limit": 150_000,
                                                       "calls_used": 3, "call_limit": 30, "stopped_by": None}
    from agent_runtime.lens.budget import budget_view

    view = budget_view(store, {"monitor_id": "status"}, T0)  # the RPC reads the real clock's day
    assert view["monitor"]["today"] == {"tokens": 2_212}
    assert view["lens"]["today"] == {"tokens": 2_212, "turns": 1}


def test_a_notify_receipt_carries_no_budget(door):
    store = LensStore()
    store.create(_monitor(level="notify"))
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    store.save_episode(_episode(1))

    assert _forge().tick() == ["notified"]
    assert store.receipt(_episode(1).id)["budget"] is None


@pytest.mark.parametrize("scope", ["monitor", "lens"])
def test_a_day_over_its_tokens_downgrades_the_next_investigate_to_a_notify(door, scope):
    store = _armed_store(1, 2)
    params = {"scope": scope, "limits": {"daily_tokens": 3_000}} | ({"monitor_id": "status"}
                                                                     if scope == "monitor" else {})
    assert _rpc("runtime.lens.budget.set", params)["result"]
    door.during, _ = _spending(1_000, 2_000)

    assert sorted(_forge().tick()) == ["budget_spent", "notified_over_budget"]
    assert len(door.calls) == 1
    # The next UTC day starts fresh: the turn runs again (and lands on the same small daily limit).
    store.save_episode(_episode(3))
    assert _forge(lambda: T0 + timedelta(days=1)).tick() == ["budget_spent"]
    assert len(door.calls) == 2


def test_the_episodes_ceiling_never_exceeds_what_the_monitor_has_left_today(door):
    from agent_runtime.lens.budget import episode_limits, record_spend

    store = _armed_store()
    _rpc("runtime.lens.budget.set", {"scope": "monitor", "monitor_id": "status",
                                     "limits": {"daily_tokens": 10_000, "episode_calls": 5}})
    record_spend(store, episode_id="e" * 64, monitor_id="status", started_ms=int(T0.timestamp() * 1000),
                 summary={"tokens_used": 7_000, "calls_used": 3})

    assert episode_limits(store, "status", T0) == (3_000, 5)


# --- editing the limits -----------------------------------------------------------


def _limits(view: dict, part: str) -> dict:
    return {key: (row["value"], row["source"]) for key, row in view[part]["limits"].items()}


def test_limits_set_over_the_rpc_survive_a_restart_and_win_over_config(tmp_path, monkeypatch):
    from agent_runtime.config.loader import harness_root_config_path

    path = harness_root_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("agent_runtime:\n  lens:\n    episode_token_budget: 90000\n    daily_token_budget: 900000\n",
                    encoding="utf-8")
    _armed_store()
    _rpc("runtime.lens.budget.set", {"scope": "lens", "limits": {"daily_tokens": 1_000_000, "daily_turns": 12}})
    workspace = _rpc("runtime.lens.budget.set", {"scope": "workspace", "workspace_id": "ws_a",
                                                 "limits": {"episode_calls": 12, "episode_tokens": 40_000}})
    assert _limits(workspace["result"], "workspace") == {
        "episode_tokens": (40_000, "workspace"), "episode_calls": (12, "workspace"), "daily_tokens": (600_000, "config")}
    with LensStore().connection() as conn:  # the monitor belongs to ws_a
        conn.execute("UPDATE monitors SET workspace_id = 'ws_a' WHERE monitor_id = 'status'")
    _rpc("runtime.lens.budget.set", {"scope": "monitor", "monitor_id": "status", "limits": {"episode_tokens": 20_000}})

    # A restart: a new store over the same file reads the same limits.
    view = _rpc("runtime.lens.budget.get", {"monitor_id": "status"})["result"]
    assert _limits(view, "lens") == {"daily_tokens": (1_000_000, "lens"), "daily_turns": (12, "lens")}
    assert _limits(view, "monitor") == {"episode_tokens": (20_000, "monitor"), "episode_calls": (12, "workspace"),
                                        "daily_tokens": (600_000, "config")}
    assert view["workspace"]["workspace_id"] == "ws_a"

    cleared = _rpc("runtime.lens.budget.set", {"scope": "monitor", "monitor_id": "status",
                                               "limits": {"episode_tokens": None}})["result"]
    assert _limits(cleared, "monitor")["episode_tokens"] == (40_000, "workspace")
    _rpc("runtime.lens.budget.set", {"scope": "lens", "limits": {"daily_tokens": None}})
    assert _limits(_rpc("runtime.lens.budget.get", {})["result"], "lens")["daily_tokens"] == (900_000, "config")


@pytest.mark.parametrize("params, reason, detail", [
    ({"scope": "lens", "limits": {"episode_tokens": 5_000}}, "unknown_key", "episode_tokens"),
    ({"scope": "monitor", "monitor_id": "status", "limits": {"episode_calls": 1}}, "invalid_integer", "episode_calls"),
    ({"scope": "monitor", "monitor_id": "status", "limits": {"daily_tokens": 5.0}}, "invalid_integer", "daily_tokens"),
    ({"scope": "monitor", "limits": {"daily_tokens": 5}}, "missing_key", "monitor_id"),
    ({"scope": "everyone", "limits": {}}, "unknown_enum", "scope"),
])
def test_a_bad_limit_is_refused_and_names_its_field(params, reason, detail):
    _armed_store()
    error = _rpc("runtime.lens.budget.set", params)["error"]
    assert (error["data"]["reason"], error["data"]["detail"]) == (reason, detail)
    assert _limits(_rpc("runtime.lens.budget.get", {"monitor_id": "status"})["result"], "monitor")[
        "episode_calls"] == (30, "config")


def test_the_edited_lens_turn_budget_is_the_one_admission_reads(door):
    _armed_store(1, 2)
    _rpc("runtime.lens.budget.set", {"scope": "lens", "limits": {"daily_turns": 1}})

    assert sorted(_forge().tick()) == ["forged", "notified_over_budget"]

