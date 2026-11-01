"""Without ``serve_registry`` (the phone wheel) an attempt a
killed app left ``generating`` is pruned on the next claim, so its subject is not
``capacity_limited`` until the 7-day sweep."""
import os
import subprocess
import sys
import time

from agent_runtime.console_suggestions.store import SuggestionStore, single_process_probe

SUBJECT = {"session_id": "s"}


def _store(path, *, pid=None, token=None):
    store = SuggestionStore(path)
    store.probe = single_process_probe(pid=pid, token=token)
    if pid is not None:
        store.pid = pid
    return store


_BINDING = """
import sys
if sys.argv[1] == "phone":
    sys.modules["agent_runtime.serve_registry"] = None
from agent_runtime.console_suggestions import store
print(store.default_process_probe is store.single_process_probe)
"""


def _bound_stand_in(edition):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    done = subprocess.run([sys.executable, "-c", _BINDING, edition], cwd=root, capture_output=True,
                          text=True, timeout=120, check=True)
    return done.stdout.strip()


def test_without_serve_registry_the_store_binds_the_single_process_probe():
    assert _bound_stand_in("phone") == "True"
    # positive control: with the registry present the desktop probe is bound, not the stand-in
    assert _bound_stand_in("desktop") == "False"


def test_an_attempt_left_generating_by_an_earlier_process_on_the_same_pid_is_pruned(tmp_path):
    earlier = _store(tmp_path / "derived.db", pid=os.getpid(), token="earlier-process")
    assert earlier.claim("old", SUBJECT, time.time()) == "claimed"
    current = _store(tmp_path / "derived.db")
    assert current.claim("new", SUBJECT, time.time()) == "claimed"
    assert current.read("old")["state"] == "unavailable"
    assert current.read("old")["reason"] == "uncertain_dispatch"


def test_an_attempt_left_generating_by_another_pid_is_pruned(tmp_path):
    earlier = _store(tmp_path / "derived.db", pid=os.getpid() + 100000, token="earlier-process")
    assert earlier.claim("old", SUBJECT, time.time()) == "claimed"
    current = _store(tmp_path / "derived.db")
    assert current.claim("new", SUBJECT, time.time()) == "claimed"
    assert current.read("old")["reason"] == "uncertain_dispatch"


def test_this_process_own_attempt_stays_generating(tmp_path):
    # positive control for the two above: the same bytes from THIS process are live
    store = _store(tmp_path / "derived.db")
    assert store.claim("old", SUBJECT, time.time()) == "claimed"
    again = _store(tmp_path / "derived.db")
    assert again.claim("new", SUBJECT, time.time()) == "capacity_limited"
    assert again.read("old")["state"] == "generating"
