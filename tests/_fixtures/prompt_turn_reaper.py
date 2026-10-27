"""Ends every ``tui-prompt`` turn thread a test leaves running, before the test's patches are undone.

``prompt.submit`` returns ``streaming`` and leaves its turn to a thread (``_run_after_agent_ready``).
A test that asserts only on the RPC answer returns while that thread is still going: with no
``agent_ready`` on the session it runs the turn against the fake agent at once, with one it waits for
a build the test stubbed out. Either way its end-of-turn ``session.info`` (cwd, branch) lands in
whichever later test has ``_emit`` patched (FORK-NOTIFICATION-POLLER-REQUEUE: ``msg-id-trunc-sid``'s
frame reached the notification poller test's capture). At teardown this cancels each such turn,
wakes a waiting one so it takes the cancel branch now, and joins it.

Registered in ``tests/tui_gateway/conftest.py`` (imported, not ``pytest_plugins`` — see
``tests/conftest.py``).
"""
import gc
import threading

import pytest

_TURN_THREAD = "tui-prompt"
_JOIN_TIMEOUT = 5.0


def _session_of(thread: threading.Thread) -> dict | None:
    """The session dict whose ``_run_thread`` is *thread* (``prompt.submit`` stores the handle)."""
    for ref in gc.get_referrers(thread):
        if isinstance(ref, dict) and ref.get("_run_thread") is thread:
            return ref
    return None


def end_leaked_turn_threads(before: set[threading.Thread]) -> list[threading.Thread]:
    """Cancel and join every live ``tui-prompt`` thread not in *before*; returns the ones still alive."""
    stuck = []
    for thread in threading.enumerate():
        if thread in before or thread.name != _TURN_THREAD or not thread.is_alive():
            continue
        session = _session_of(thread)
        if session is not None:
            session["_turn_cancel_requested"] = True
            ready = session.get("agent_ready")
            if ready is not None:
                ready.set()
        thread.join(timeout=_JOIN_TIMEOUT)
        if thread.is_alive():
            stuck.append(thread)
    return stuck


@pytest.fixture(autouse=True)
def _reap_prompt_turn_threads(monkeypatch):
    # Depends on monkeypatch so this teardown runs BEFORE the test's patches are undone: the
    # cancelled turn's last frame goes to the test's own ``_emit``, never a later test's.
    before = set(threading.enumerate())
    yield
    stuck = end_leaked_turn_threads(before)
    assert not stuck, f"{len(stuck)} tui-prompt turn thread(s) outlived the test and could not be ended"
