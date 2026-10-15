"""Fork-owned tests moved out of ``tests/hermes_cli/test_kanban_db.py`` (lane CARRY).

The crash artifact rides upstream's ``on_kanban_worker_exited`` observer, registered by the
eternia-harness plugin (lane h13-del, 2026-09-29): ``kanban_db_dispatch.py`` is at upstream
bytes, so the artifact is found under ``<board logs>/crashes/`` rather than named in the
``crashed`` event.
"""

from __future__ import annotations
import hermes_cli.kanban_db_dispatch as _owner_hermes_cli_kanban_db_dispatch
import hermes_cli.kanban_db_workspace as _owner_hermes_cli_kanban_db_workspace
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli.plugins import get_plugin_manager

from tests.hermes_cli.test_kanban_db import (  # noqa: F401 — upstream names the moved tests use
    kanban_home,
)


@pytest.fixture
def crash_evidence_hook(kanban_home):
    """The eternia-harness plugin's ``on_kanban_worker_exited`` callback, subscribed by the
    plugin's own ``register()`` through upstream discovery (not appended by hand)."""
    mgr = get_plugin_manager()
    saved = {k: list(v) for k, v in mgr._hooks.items()}
    mgr.discover_and_load()
    names = [getattr(cb, "__name__", "") for cb in mgr._hooks.get("on_kanban_worker_exited", [])]
    assert names.count("record_kanban_crash_evidence") == 1, names
    try:
        yield
    finally:
        mgr._hooks = saved


def _artifacts(tid):
    return sorted((kb.worker_logs_dir() / "crashes").glob(f"{tid}-*.json"))


def test_detect_crashed_workers_writes_supervisor_lost_child_artifact(
    kanban_home, tmp_path, monkeypatch, crash_evidence_hook,
):
    """Supervisor PID disappears while a detached child / sidecar process
    keeps running. The dispatcher must:

      * preserve the child's pid/cmd/cwd/log path
      * bounded-tail and redact stdout/stderr
      * write a durable JSON crash artifact under ``logs/crashes/``
      * classify the record as ``supervisor_lost_child`` (not just
        ``process_failed``)
      * stamp the artifact with the closed run's id, claimer and event kind
      * keep all artifact text free of Bearer/JWT/signed-URL tokens
    """
    import json
    import hermes_cli.kanban_db as _kb

    workspace = tmp_path / "ws-task"
    workspace.mkdir()
    sidecar_dir = workspace / ".hermes" / "sidecars"
    sidecar_dir.mkdir(parents=True)

    live_child_pid = 424242  # detached child still running
    dead_supervisor_pid = 999111

    # Sidecar manifest the worker would have dropped before backgrounding
    # its long-running child (think: ffmpeg encode, training loop, etc.).
    sidecar_log = workspace / "child.log"
    sidecar_log.write_bytes(
        b"[child] iter 1\n[child] iter 2 token=eyJa.bbb-ccc.ddd_eee\n"
    )
    (sidecar_dir / "encoder.json").write_text(
        json.dumps({
            "pid": live_child_pid,
            "name": "encoder",
            "cmd": ["ffmpeg", "-i", "in.mov", "out.mov"],
            "cwd": str(workspace),
            "log_path": str(sidecar_log),
        }),
        encoding="utf-8",
    )

    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="encode", assignee="worker")
        host_prefix = _kb._claimer_id().split(":", 1)[0]
        kb.claim_task(conn, tid, claimer=f"{host_prefix}:s")
        kbd._set_worker_pid(conn, tid, dead_supervisor_pid)
        _owner_hermes_cli_kanban_db_workspace.set_workspace_path(conn, tid, str(workspace))
        conn.execute(
            "UPDATE tasks SET started_at = ? WHERE id = ?",
            (int(_kb.time.time()) - _kb.DEFAULT_CRASH_GRACE_SECONDS - 1, tid),
        )
        conn.commit()

        # Drop a worker log laden with credentials so we can prove the
        # tail makes it into the artifact AND is redacted.
        log_path = _kb.worker_log_path(tid)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_bytes(
            b"[sup] booting...\n"
            b"Authorization: Bearer eyJaaa.bbb-ccc.ddd_eee\n"
            b"x-api-key: sk-live-1234567890ABCDEFG\n"
            b"detached encoder pid=424242\n"
            b"GET /s3/obj?X-Amz-Signature=deadbeefcafef00d&Expires=1700000000\n"
        )

        # Simulate "supervisor died, child still alive": only the dead
        # supervisor pid is dead.
        def _alive(pid):
            return int(pid) == live_child_pid

        monkeypatch.setattr(_kb, "_pid_alive", _alive)

        crashed = _owner_hermes_cli_kanban_db_dispatch.detect_crashed_workers(conn)
        assert crashed == [tid]

        runs = kb.list_runs(conn, tid)
        closed = [r for r in runs if r.outcome == "crashed"]
        assert closed, f"expected one closed crashed run; got {runs!r}"
        found = _artifacts(tid)
        assert len(found) == 1, f"expected one crash artifact, got {found!r}"
        evidence_path = str(found[0])

        artifact = Path(evidence_path)
        assert artifact.exists(), f"artifact missing on disk: {artifact}"
        # Crashes folder should sit under the board's logs dir.
        assert artifact.parent.name == "crashes"
        assert artifact.parent.parent == _kb.worker_logs_dir()

        doc = json.loads(artifact.read_text(encoding="utf-8"))
        # Deterministic, redaction-safe schema.
        assert doc["task_id"] == tid
        assert doc["classification"] == "supervisor_lost_child"
        assert doc["worker_pid"] == dead_supervisor_pid
        assert doc["profile"] == "worker"
        assert doc["run_id"] == closed[-1].id
        assert doc["event_kind"] == "crashed"
        assert doc["claimer"], "the run row's claim_lock survives the reclaim"
        assert "timestamp" in doc and isinstance(doc["timestamp"], str)
        assert "captured_at_epoch" in doc

        sidecars = doc.get("sidecars", [])
        assert sidecars, "expected sidecar entries to be discovered"
        sc = sidecars[0]
        assert sc["pid"] == live_child_pid
        assert sc["alive"] is True
        assert sc["cmd"] == ["ffmpeg", "-i", "in.mov", "out.mov"]
        assert sc["log_path"] == str(sidecar_log)
        # Sidecar tail captured + redacted.
        assert "iter 2" in sc.get("log_tail", "")
        assert "eyJa.bbb-ccc.ddd_eee" not in sc.get("log_tail", "")

        # Worker log tail present + fully redacted.
        tail = doc.get("worker_log_tail", "")
        assert "detached encoder pid=424242" in tail
        for forbidden in [
            "eyJaaa.bbb-ccc.ddd_eee",
            "sk-live-1234567890ABCDEFG",
            "deadbeefcafef00d",
            "1700000000",
        ]:
            assert forbidden not in tail, (
                f"worker_log_tail leaked {forbidden!r}: {tail!r}"
            )
        # Whole artifact, recursively, must be free of those secrets.
        whole = artifact.read_text(encoding="utf-8")
        for forbidden in [
            "eyJaaa.bbb-ccc.ddd_eee",
            "sk-live-1234567890ABCDEFG",
            "deadbeefcafef00d",
            "1700000000",
        ]:
            assert forbidden not in whole

    finally:
        conn.close()


def test_detect_crashed_workers_process_failed_when_no_live_sidecar(
    kanban_home, tmp_path, monkeypatch, crash_evidence_hook,
):
    """When neither supervisor nor any sidecar is alive, the crash record
    is classified ``process_failed`` (and still written) — distinct from
    the supervisor-lost-child case where reconciliation might still be
    possible from the surviving child."""
    import json
    import hermes_cli.kanban_db as _kb

    workspace = tmp_path / "ws-plain"
    workspace.mkdir()
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="plain", assignee="worker")
        host_prefix = _kb._claimer_id().split(":", 1)[0]
        kb.claim_task(conn, tid, claimer=f"{host_prefix}:s")
        kbd._set_worker_pid(conn, tid, 7777777)
        _owner_hermes_cli_kanban_db_workspace.set_workspace_path(conn, tid, str(workspace))
        conn.execute(
            "UPDATE tasks SET started_at = ? WHERE id = ?",
            (int(_kb.time.time()) - _kb.DEFAULT_CRASH_GRACE_SECONDS - 1, tid),
        )
        conn.commit()

        monkeypatch.setattr(_kb, "_pid_alive", lambda _p: False)

        crashed = _owner_hermes_cli_kanban_db_dispatch.detect_crashed_workers(conn)
        assert crashed == [tid]

        # Even without sidecars, an artifact is still written so operators
        # have a single canonical place to look.
        found = _artifacts(tid)
        assert len(found) == 1
        path = str(found[0])
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        assert doc["classification"] == "process_failed"
        assert doc["sidecars"] == []
    finally:
        conn.close()
