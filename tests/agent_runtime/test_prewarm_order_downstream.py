"""h-prewarm-order: an opened chat is prewarmed ahead of boot work, a turn the
serve has ACCEPTED but not yet anchored stops a prewarm, and the accept -> anchor
span is receipted.

Live case (2026-10-06 01:24:53-01:25:05): the boot item for the previously open
chat held the one prewarm worker 11.7 s, the opened chat queued FIFO behind it,
then ran beside turn ``5377d205``, which was accepted at 04.23 and anchored at
04.909 -- invisible to ``chat_turns_admitted()``.
"""

from __future__ import annotations

import logging
import queue
import threading
from types import SimpleNamespace

import pytest

from tests._downstream.split_package_source import patch_where_bound

from agent_runtime import persona_chat_actor_prewarm as prewarm_module
from agent_runtime import persona_chat_continuity, turn_activity
from agent_runtime.persona_chat_actor_prewarm import (
    OUTCOME_PREEMPTED_BY_OPEN,
    OUTCOME_SKIPPED_NO_CHAT_ROOT,
    OUTCOME_SKIPPED_TURN_ACTIVE,
    OUTCOME_WARMED,
    PRIORITY_BOOT,
    prewarm_chat_actor,
    request_chat_actor_prewarm,
)
from agent_runtime.persona_chat_continuity import PersonaChatRuntimeRegistry


@pytest.fixture
def worker(monkeypatch):
    """A registry, a fresh queue, and a way to drain it on a thread of our own."""

    registry = PersonaChatRuntimeRegistry()
    patch_where_bound(
        monkeypatch, persona_chat_continuity, "persona_chat_runtime_registry", lambda: registry
    )
    monkeypatch.setattr(prewarm_module, "_queue", queue.PriorityQueue())
    monkeypatch.setattr(prewarm_module, "_pending", {})
    monkeypatch.setattr(prewarm_module, "_links", {})
    monkeypatch.setattr(prewarm_module, "_deferred_until_idle", {})
    monkeypatch.setattr(prewarm_module, "_running_root", None)
    monkeypatch.setattr(prewarm_module, "_running_priority", None)
    monkeypatch.setattr(prewarm_module, "_ensure_worker", lambda: None)

    def drain():
        thread = threading.Thread(target=prewarm_module._drain, daemon=True)
        thread.start()
        prewarm_module._queue.join()

    return drain


def test_an_opened_chat_runs_ahead_of_queued_boot_items(worker, monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", lambda root: ran.append(root) or OUTCOME_WARMED)

    assert request_chat_actor_prewarm("boot_a", priority=PRIORITY_BOOT) == "started"
    assert request_chat_actor_prewarm("boot_b", priority=PRIORITY_BOOT) == "started"
    assert request_chat_actor_prewarm("opened") == "started"
    worker()

    assert ran == ["opened", "boot_a", "boot_b"]
    assert not prewarm_module._pending


def test_opening_a_chat_the_boot_pass_queued_promotes_it_and_it_runs_once(worker, monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", lambda root: ran.append(root) or OUTCOME_WARMED)

    request_chat_actor_prewarm("boot_a", priority=PRIORITY_BOOT)
    request_chat_actor_prewarm("boot_b", priority=PRIORITY_BOOT)
    assert request_chat_actor_prewarm("boot_b") == "promoted"
    assert request_chat_actor_prewarm("boot_b") == "already_running"
    worker()

    assert ran == ["boot_b", "boot_a"]


def test_a_boot_item_yields_to_an_open_and_is_requeued_behind_it(worker, monkeypatch):
    """Preempt-and-requeue: the boot item, at its yield point, sees the open
    queued after it started, stands down, and runs again after the open."""

    ran: list[tuple[str, str]] = []

    def prewarm(root):
        if root == "boot_a" and not ran:
            request_chat_actor_prewarm("opened")  # the operator opens a chat now
        outcome = prewarm_module._stand_down_outcome() or OUTCOME_WARMED
        ran.append((root, outcome))
        return outcome

    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", prewarm)

    request_chat_actor_prewarm("boot_a", priority=PRIORITY_BOOT)
    worker()

    assert ran == [
        ("boot_a", OUTCOME_PREEMPTED_BY_OPEN),
        ("opened", OUTCOME_WARMED),
        ("boot_a", OUTCOME_WARMED),
    ]
    assert not prewarm_module._pending


@pytest.mark.parametrize(
    "first, second, second_priority",
    [("opened", "opened_later", None), ("boot_a", "boot_b", PRIORITY_BOOT)],
    ids=["an_open_is_never_preempted", "a_boot_item_never_yields_to_boot"],
)
def test_only_an_open_preempts_and_only_a_boot_item(worker, monkeypatch, first, second, second_priority):
    ran: list[tuple[str, str]] = []
    kwargs = {} if second_priority is None else {"priority": second_priority}

    def prewarm(root):
        if root == first:
            request_chat_actor_prewarm(second, **kwargs)
        outcome = prewarm_module._stand_down_outcome() or OUTCOME_WARMED
        ran.append((root, outcome))
        return outcome

    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", prewarm)

    request_chat_actor_prewarm(first, **({"priority": PRIORITY_BOOT} if first.startswith("boot") else {}))
    worker()

    assert ran == [(first, OUTCOME_WARMED), (second, OUTCOME_WARMED)]


def test_an_opens_link_refresh_starts_at_the_gesture_and_the_item_waits_for_it(worker, monkeypatch):
    """The app-function ask leaves at the open, not when the item reaches the
    worker, so a send arriving behind a busy worker finds the catalog held; the
    item still prepares only after the reply."""

    from agent_runtime import launcher_app_functions as app

    asked, answer = threading.Event(), threading.Event()
    order: list[str] = []

    def refresh(link):
        asked.set()
        assert answer.wait(5)
        order.append("refreshed")

    monkeypatch.setattr(app, "refresh_app_function_tools", refresh)
    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", lambda root: order.append(root) or OUTCOME_WARMED)

    request_chat_actor_prewarm("opened", launcher_link=app.LauncherLink(sink=object(), origin=app.ORIGIN_LOCAL))
    assert asked.wait(5), "no ask left at the gesture (no worker has run yet)"
    threading.Timer(0.2, answer.set).start()
    worker()

    assert order == ["refreshed", "opened"]


# ── an accepted, not yet anchored turn ───────────────────────────────────────


def _reached_prepare(monkeypatch) -> list[str]:
    reached: list[str] = []

    def _prepare(root, instance):
        reached.append(root)
        raise prewarm_module._PrewarmRefused(OUTCOME_SKIPPED_NO_CHAT_ROOT)

    monkeypatch.setattr(prewarm_module, "_prepare", _prepare)
    return reached


def test_an_accepted_turn_stops_a_prewarm_before_it_prepares(worker, monkeypatch):
    reached = _reached_prepare(monkeypatch)

    hold = turn_activity.AcceptedTurn("chat-1")
    try:
        assert turn_activity.chat_turns_admitted() == 0
        assert prewarm_chat_actor("root_1") == OUTCOME_SKIPPED_TURN_ACTIVE
        assert reached == []
    finally:
        hold.release()
    assert prewarm_chat_actor("root_1") == OUTCOME_SKIPPED_NO_CHAT_ROOT
    assert reached == ["root_1"]


def test_a_turn_accepted_while_the_prewarm_prepares_stops_its_construction(worker, monkeypatch):
    holds: list[turn_activity.AcceptedTurn] = []

    def _prepare(root, instance):
        holds.append(turn_activity.AcceptedTurn("chat-1"))  # the send lands now
        return object(), SimpleNamespace(prewarm=lambda request: pytest.fail("constructed"))

    monkeypatch.setattr(prewarm_module, "_prepare", _prepare)
    try:
        assert prewarm_chat_actor("root_1") == OUTCOME_SKIPPED_TURN_ACTIVE
    finally:
        for hold in holds:
            hold.release()


def test_the_anchor_takes_the_turn_over_from_the_accept_with_no_gap():
    hold = turn_activity.AcceptedTurn("chat-1")
    with turn_activity.accepted_turn_scope(hold):
        assert turn_activity.chat_turns_accepted() >= 1
        before = turn_activity.chat_turns_accepted()
        with turn_activity.admitted_turn():
            assert turn_activity.chat_turns_admitted() >= 1
            assert turn_activity.chat_turns_accepted() == before - 1
    assert turn_activity.chat_turns_accepted() == before - 1


def test_a_request_that_never_reaches_a_handler_releases_its_hold():
    hold = turn_activity.AcceptedTurn("chat-1")
    before = turn_activity.chat_turns_accepted()
    with turn_activity.accepted_turn_scope(hold):
        pass
    assert turn_activity.chat_turns_accepted() == before - 1


# ── the accept -> anchor receipt, through the serve's own lanes ──────────────


def test_a_chat_turn_through_the_pool_receipts_accept_to_anchor(monkeypatch, caplog):
    """The real ``_spawn_chat_turn`` -> ``_run`` -> handler path: the hold is
    taken at the submit, the anchor logs one receipt and the count returns."""

    from hermes_cli.harness_parts.serve.lanes import ArgvLanes
    from hermes_cli.harness_parts.serve.request_pool import TurnClaims

    seen: dict[str, int] = {}

    def dispatch(argv):
        seen["accepted_in_handler_before_anchor"] = turn_activity.chat_turns_accepted()
        with turn_activity.admitted_turn():
            seen["accepted_after_anchor"] = turn_activity.chat_turns_accepted()
        return 0

    submitted: list = []
    frames: list = []
    session = SimpleNamespace(
        inflight_lock=threading.RLock(), inflight={}, inflight_futures={}, drain_state=None,
        pool=SimpleNamespace(submit_turn=lambda fn, request: submitted.append((fn, request))),
        turn_claims=TurnClaims(),
        frames=SimpleNamespace(emit=frames.append), dispatch=dispatch,
        serve_request_home=None, read_cache=None,
        stdout_proxy=SimpleNamespace(flush_request=lambda rid: None),
        stderr_proxy=SimpleNamespace(flush_request=lambda rid: None),
        _owner_of=lambda connection: "stdio",
        _bind_launcher_link=lambda request, sink: None,
    )
    for name in ("_run", "_execute_request", "_dispatch_guarded", "_reply_exit"):
        setattr(session, name, getattr(ArgvLanes, name).__get__(session))

    base = turn_activity.chat_turns_accepted()
    sink = SimpleNamespace(emit=frames.append)
    ArgvLanes._spawn_chat_turn(
        session, sink, None, "chat-req-1", ["harness", "mission-chat", "message"], ""
    )
    assert turn_activity.chat_turns_accepted() == base + 1, "the accept took no hold"

    fn, request = submitted[0]
    with caplog.at_level(logging.INFO, logger=turn_activity.__name__):
        fn(request)

    assert seen == {
        "accepted_in_handler_before_anchor": base + 1,
        "accepted_after_anchor": base,
    }
    assert turn_activity.chat_turns_accepted() == base
    lines = [r.getMessage() for r in caplog.records if "chat_turn_accept_to_anchor" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].startswith("chat_turn_accept_to_anchor request=chat-req-1 queue_ms=")
    for field in ("link_ms=", "dispatch_ms=", "total_ms="):
        assert field in lines[0]


def test_active_turn_yield_requeues_once_at_idle_boundary(worker, monkeypatch):
    ran = []
    def warm(root):
        ran.append(root)
        return OUTCOME_SKIPPED_TURN_ACTIVE if turn_activity.chat_turns_admitted() else OUTCOME_WARMED
    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", warm)
    with turn_activity.admitted_turn("turn"):
        request_chat_actor_prewarm("yielded", priority=PRIORITY_BOOT)
        worker()
        assert ran == ["yielded"]
        assert prewarm_module._pending == {"yielded": PRIORITY_BOOT}
        assert prewarm_module._queue.empty()
    prewarm_module._queue.join()
    assert ran == ["yielded", "yielded"]
    assert not prewarm_module._pending
    assert not prewarm_module._deferred_until_idle
