"""A cron job's finished run wakes the persona chat that created it (``agent_runtime/cron_wake.py``).

ADR 0015 step 1, 2026-10-12. Bind at the ``cronjob`` create result, wake on the finish through
``process_registry.completion_queue``, one durable checkpoint. Upstream's store is read through
its public ``cron.jobs`` door, stubbed here per test.

Killing mutations (each applied, red recorded in the commit body, reverted):
* ``poll_cron_wakes`` drops ``row["last_run_at"] = run_at``        -> the once-per-run test red.
* ``observe_cronjob_result`` drops the ``args.get("action") != "create"`` arm -> the list test red.
* ``_PROCESS_LIKE_EVENTS`` drops ``"cron_job_finished"``           -> the drain membership test red.
"""

from __future__ import annotations

import json
import queue
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_runtime import cron_wake

JOB = "job_abc123"
ROOT = "persona_chat_neko_0001"


@pytest.fixture
def checkpoint(tmp_path, monkeypatch):
    path = tmp_path / "work" / cron_wake.CHECKPOINT_FILENAME
    monkeypatch.setattr(cron_wake, "_checkpoint_path", lambda: path)
    return path


@pytest.fixture
def routed(monkeypatch):
    """The tool worker thread's routing: the persona root the mission-chat lease bound."""
    from tools.approval_context import reset_current_session_key, set_current_session_key

    token = set_current_session_key(ROOT)
    yield ROOT
    reset_current_session_key(token)


@pytest.fixture
def completion_queue(monkeypatch):
    from tools import process_registry as pr

    q: queue.Queue = queue.Queue()
    monkeypatch.setattr(pr.process_registry, "completion_queue", q)
    return q


class _Store:
    """``cron.jobs`` as the wake reads it: one job per (home, id), one output dir per home."""

    def __init__(self, tmp_path: Path):
        self.jobs: dict[tuple[str, str], dict] = {}
        self.root = tmp_path
        self.active_home = ""

    @contextmanager
    def use_cron_store(self, home):
        before, self.active_home = self.active_home, str(home)
        try:
            yield
        finally:
            self.active_home = before

    def get_job(self, job_id):
        return self.jobs.get((self.active_home, job_id))

    def get_cron_output_dir(self):
        return self.root / "out" / Path(self.active_home).name

    def save_output(self, home, job_id, stamp, text):
        d = self.root / "out" / Path(home).name / job_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stamp}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def store(tmp_path, monkeypatch):
    import cron.jobs as jobs

    s = _Store(tmp_path)
    monkeypatch.setattr(jobs, "use_cron_store", s.use_cron_store)
    monkeypatch.setattr(jobs, "get_job", s.get_job)
    monkeypatch.setattr(jobs, "get_cron_output_dir", s.get_cron_output_dir)
    return s


def _create_result(job_id=JOB, name="morning orders", success=True):
    return json.dumps({"success": success, "job_id": job_id, "name": name})


# ── bind ─────────────────────────────────────────────────────────────────────


def test_a_create_binds_the_job_to_the_chat_that_made_it(checkpoint, routed):
    assert cron_wake.observe_cronjob_result("cronjob", {"action": "create"}, _create_result()) is True
    rows = json.loads(checkpoint.read_text())["jobs"]
    assert rows[JOB]["session_key"] == ROOT and rows[JOB]["name"] == "morning orders"
    assert rows[JOB]["last_run_at"] is None and rows[JOB]["home"]


def test_only_a_successful_create_binds(checkpoint, routed):
    assert cron_wake.observe_cronjob_result("cronjob", {"action": "list"}, _create_result()) is False
    assert cron_wake.observe_cronjob_result("cronjob", {"action": "create"}, _create_result(success=False)) is False
    assert cron_wake.observe_cronjob_result("terminal", {"action": "create"}, _create_result()) is False
    assert cron_wake.observe_cronjob_result("cronjob", {"action": "create"}, "not json") is False
    assert not checkpoint.exists()


def test_the_upstream_action_tool_name_binds_too_and_first_binding_wins(checkpoint, routed, monkeypatch):
    assert cron_wake.observe_cronjob_result("cronjob_manage", {"action": "create"}, _create_result()) is True
    from tools.approval_context import reset_current_session_key, set_current_session_key

    token = set_current_session_key("persona_chat_other")
    try:
        assert cron_wake.observe_cronjob_result("cronjob", {"action": "create"}, _create_result()) is False
    finally:
        reset_current_session_key(token)
    assert json.loads(checkpoint.read_text())["jobs"][JOB]["session_key"] == ROOT


def test_a_create_outside_any_session_binds_nothing(checkpoint, monkeypatch):
    monkeypatch.setattr(cron_wake, "_routing", lambda: {"session_key": "", "parent_session_id": "", "home": "/h"})
    assert cron_wake.observe_cronjob_result("cronjob", {"action": "create"}, _create_result()) is False
    assert not checkpoint.exists()


# ── wake ─────────────────────────────────────────────────────────────────────


def _bind(checkpoint, home, job_id=JOB):
    rows = {job_id: {"job_id": job_id, "name": "morning orders", "home": home, "session_key": ROOT,
                     "parent_session_id": "", "bound_at": 1.0, "last_run_at": None, "expires_at": 10 ** 12}}
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps({"version": 1, "jobs": rows}))


def test_a_finished_run_wakes_the_chat_once_per_run(checkpoint, store, completion_queue, tmp_path):
    home = str(tmp_path / "homes" / "neko")
    _bind(checkpoint, home)
    store.jobs[(home, JOB)] = {"id": JOB, "name": "morning orders", "last_run_at": None, "last_status": None}

    assert cron_wake.poll_cron_wakes() == 0 and completion_queue.empty()  # not run yet

    store.jobs[(home, JOB)].update(last_run_at="2026-10-12T07:00:00Z", last_status="ok")
    store.save_output(home, JOB, "2026-10-12_07-00-00", "Three orders need a reply: #41, #42, #45.")
    assert cron_wake.poll_cron_wakes() == 1
    evt = completion_queue.get_nowait()
    assert evt["type"] == "cron_job_finished" and evt["session_key"] == ROOT and evt["job_id"] == JOB
    assert evt["status"] == "ok" and evt["run_at"] == "2026-10-12T07:00:00Z"
    assert "#42" in evt["output"]
    assert evt["session_id"] == cron_wake.wake_identity(JOB, "2026-10-12T07:00:00Z")

    # The same run never wakes twice; the cursor advanced in the checkpoint.
    assert cron_wake.poll_cron_wakes() == 0 and completion_queue.empty()
    assert json.loads(checkpoint.read_text())["jobs"][JOB]["last_run_at"] == "2026-10-12T07:00:00Z"

    # A recurring job's NEXT run wakes again, with its own identity.
    store.jobs[(home, JOB)].update(last_run_at="2026-10-13T07:00:00Z", last_status="error", last_error="provider 503")
    assert cron_wake.poll_cron_wakes() == 1
    evt2 = completion_queue.get_nowait()
    assert evt2["status"] == "error" and evt2["error"] == "provider 503" and evt2["session_id"] != evt["session_id"]


def test_the_job_is_read_from_the_home_it_was_created_under(checkpoint, store, completion_queue, tmp_path):
    neko, base = str(tmp_path / "homes" / "neko"), str(tmp_path / "homes" / "base")
    _bind(checkpoint, neko)
    # The same id exists in ANOTHER home with a run; the binding's home has none → no wake.
    store.jobs[(base, JOB)] = {"id": JOB, "last_run_at": "2026-10-12T07:00:00Z", "last_status": "ok"}
    store.jobs[(neko, JOB)] = {"id": JOB, "last_run_at": None, "last_status": None}
    assert cron_wake.poll_cron_wakes() == 0 and completion_queue.empty()


def test_a_removed_job_drops_its_binding_and_an_unreadable_store_keeps_it(checkpoint, store, completion_queue, tmp_path, monkeypatch):
    home = str(tmp_path / "homes" / "neko")
    _bind(checkpoint, home)
    assert cron_wake.poll_cron_wakes() == 0  # get_job → None: removed
    assert json.loads(checkpoint.read_text())["jobs"] == {}

    _bind(checkpoint, home)

    def _boom(job_id):
        raise OSError("locked")

    monkeypatch.setattr(store, "get_job", _boom)
    import cron.jobs as jobs

    monkeypatch.setattr(jobs, "get_job", _boom)
    assert cron_wake.poll_cron_wakes() == 0
    assert JOB in json.loads(checkpoint.read_text())["jobs"]  # "not now" is not "gone"


def test_an_expired_binding_is_forgotten(checkpoint, store, tmp_path):
    home = str(tmp_path / "homes" / "neko")
    _bind(checkpoint, home)
    store.jobs[(home, JOB)] = {"id": JOB, "last_run_at": None, "last_status": None}
    assert cron_wake.poll_cron_wakes(now=10 ** 13) == 0
    assert json.loads(checkpoint.read_text())["jobs"] == {}


# ── render and drain membership ──────────────────────────────────────────────


def test_the_drain_treats_the_wake_as_a_process_completion_and_renders_it():
    from agent_runtime.dispatch_delivery.completions import _PROCESS_LIKE_EVENTS
    from tools.process_registry_notifications import format_process_notification

    assert "cron_job_finished" in _PROCESS_LIKE_EVENTS
    text = format_process_notification({
        "type": "cron_job_finished", "job_id": JOB, "name": "morning orders", "status": "ok",
        "run_at": "2026-10-12T07:00:00Z", "output": "Three orders need a reply.", "error": "",
    })
    assert text.startswith("[IMPORTANT: Scheduled job \"morning orders\"") and text.endswith("]")
    assert "ok" in text and "Three orders need a reply." in text and "2026-10-12T07:00:00Z" in text
    failed = cron_wake.format_cron_job_finished({"type": "cron_job_finished", "job_id": JOB, "status": "error", "error": "provider 503"})
    assert "provider 503" in failed and "(none saved)" in failed


def test_the_chat_root_resolver_accepts_the_wake(monkeypatch):
    """The owner lookup the drain runs on a process-like event sees the persona root this event names."""
    from agent_runtime.dispatch_delivery import completions

    evt = {"type": "cron_job_finished", "session_key": ROOT, "parent_session_id": ""}
    assert completions._chat_root_of_completion(evt, sender_persona=lambda root: ("neko", "inst") if root == ROOT else None) == ROOT
    assert completions._orphaned_persona_root(evt, sender_persona=lambda root: None) == ROOT
