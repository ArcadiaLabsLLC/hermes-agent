"""Bounded concurrency under source churn and cancellation, using real receipts."""
from concurrent.futures import ThreadPoolExecutor
from threading import Condition, Event
import subprocess
import sys
import time
import pytest

from tests.agent_runtime.test_console_suggestions import subject, caller, enable

pytest_plugins = ("tests.agent_runtime.test_console_suggestions",)


def test_thousand_off_roots_and_sixty_four_visible_subscribers_keep_two_real_calls(service):
    svc, _ = service
    for number in range(1000):
        assert svc.read(subject(str(number)))["state"] == "disabled"
    assert svc.pool is None and not svc.store.path.exists()
    entered = Condition()
    release = Event()
    active = []
    def generate(messages):
        with entered:
            active.append(1)
            entered.notify_all()
        assert release.wait(10)
        return {"text": "Next?", "usage": {}}
    svc.generator = generate
    enable(svc)
    try:
        for number in range(64):
            svc.subscribe(caller(str(number // 8)), subject(str(number)))
        with entered:
            assert entered.wait_for(lambda: len(active) == 2, timeout=5)
        with svc.condition:
            assert len(svc.running) == 2
            assert len(svc.pending) <= 32
            assert len(svc.subscriptions) == 64
        # Disabling does not release the slots held by actual provider calls.
        svc.settings_write({"expected_revision": svc.settings_read()["settings_revision"], "enabled": False})
        enable(svc)
        svc.subscribe(caller("new"), subject("new"))
        with svc.condition:
            assert len(svc.running) == 2
        assert len(active) == 2
        svc.release("new")
        release.set()
        with svc.condition:
            assert svc.condition.wait_for(lambda: not svc.running, timeout=5)
        assert len(active) == 2
        assert not svc.pending and not svc.states
    finally:
        release.set()


def test_two_processes_claim_one_source_once(tmp_path):
    script = """from pathlib import Path
import sys,time
from agent_runtime.console_suggestions.store import SuggestionStore
s=SuggestionStore(Path(sys.argv[1]))
print(s.claim('same-source', {'session_id':'same-chat'}, time.time()), flush=True)
time.sleep(0.2)
"""
    def run():
        return subprocess.run([sys.executable, "-c", script, str(tmp_path / "shared.db")],
            capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == ["claimed", "existing"]


@pytest.mark.timeout(90)
def test_thousand_completed_roots_bound_payloads_without_repeat_spend(service):
    from tests.agent_runtime.test_console_suggestions import observed
    svc, _ = service
    enable(svc)
    for number in range(1000):
        who = subject(str(number))
        observed(svc, who)
        svc._work(who)
        assert svc.read(who)["state"] == "ready"
    with svc.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1000
        assert db.execute("SELECT count(*) FROM attempts WHERE text IS NOT NULL").fetchone()[0] == 256
    assert len(svc.states) == 1
    assert len(svc.last_dispatch) == 1
    observed(svc, subject("0"))
    svc.generator = lambda messages: pytest.fail("evicted payload regenerated")
    svc._work(subject("0"))
    assert svc.read(subject("0"))["state"] == "none"


@pytest.mark.timeout(30)
def test_slow_auxiliary_call_has_no_fifteen_second_feature_timeout(service):
    from tests.agent_runtime.test_console_suggestions import observed
    svc, _ = service
    enable(svc)
    observed(svc, subject())
    def slow(messages):
        time.sleep(16)  # health: allow HX013 -- deliberate real-clock positive control for routes slower than the rejected 15-second feature cutoff
        return {"text": "Continue with the detailed version?", "usage": {}}
    svc.generator = slow
    svc._work(subject())
    assert svc.read(subject())["state"] == "ready"
