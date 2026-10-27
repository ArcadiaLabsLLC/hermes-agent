"""A ``prompt.submit`` test's turn thread never outlives it (FORK-NOTIFICATION-POLLER-REQUEUE).

``tests/_fixtures/prompt_turn_reaper.py`` ends the thread at teardown. The first two tests are the
leak itself, in file order: the first returns on the RPC answer while its build is still "running",
the second captures ``_emit`` and must see nothing of the first's session. The last two drive the reaper directly.
"""
import threading
import time
import types

from tests._fixtures.prompt_turn_reaper import end_leaked_turn_threads
from tui_gateway import server

_LEAK_SID = "reaper-leak-sid"


def _session(**extra):
    return {
        "agent": types.SimpleNamespace(),
        "session_key": "reaper-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        **extra,
    }


def _submit(monkeypatch, sid, session):
    server._sessions[sid] = session
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_start_agent_build", lambda *a, **k: None)
    monkeypatch.setattr(server, "_start_inflight_turn", lambda *a, **k: None)
    resp = server.handle_request(
        {"id": "1", "method": "prompt.submit", "params": {"session_id": sid, "text": "hi"}}
    )
    assert resp.get("result") is not None, resp
    return session["_run_thread"]


def test_a_submit_returns_on_the_rpc_answer(monkeypatch):
    # The stubbed build "finishes" just after the test returns, so the turn runs in the next test's
    # window — the load-dependent ordering of the original flake, made deterministic.
    ready = threading.Event()
    threading.Timer(0.3, ready.set).start()
    try:
        _submit(monkeypatch, _LEAK_SID, _session(agent_ready=ready))
    finally:
        server._sessions.pop(_LEAK_SID, None)


def test_b_a_later_capture_sees_nothing_of_the_earlier_turn(monkeypatch):
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda *args, **_kw: emitted.append(args))
    time.sleep(1.0)  # the window the earlier turn's end-of-turn frames would land in
    assert [frame for frame in emitted if _LEAK_SID in frame] == []


def test_reaper_joins_a_turn_running_against_the_fake_agent(monkeypatch):
    before = set(threading.enumerate())
    try:
        thread = _submit(monkeypatch, "reaper-run-sid", _session())
        assert end_leaked_turn_threads(before) == []
        assert not thread.is_alive()
    finally:
        server._sessions.pop("reaper-run-sid", None)


def test_reaper_cancels_a_turn_waiting_on_a_stubbed_build(monkeypatch):
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda *args, **_kw: emitted.append(args))
    before = set(threading.enumerate())
    session = _session(agent=None, agent_ready=threading.Event())
    try:
        thread = _submit(monkeypatch, "reaper-wait-sid", session)
        time.sleep(0.2)
        assert thread.is_alive()  # positive control: the stubbed build leaves it waiting
        started = time.monotonic()
        assert end_leaked_turn_threads(before) == []
        assert time.monotonic() - started < 2.0  # woken, not left to its 5 s cancel slice
        assert not thread.is_alive()
        assert ("error", "reaper-wait-sid", {"message": "Turn cancelled before the agent was ready"}) in emitted
    finally:
        server._sessions.pop("reaper-wait-sid", None)
