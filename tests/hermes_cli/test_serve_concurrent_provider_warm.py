"""RT-PREWARM-BUILD-AGENTS-READINESS-COLD S1: with the snapshot worker bound, the
serve's own provider warm runs BESIDE the cold prewarm build, not behind it.

Live 2026-10-25: a Dev turn sent 4 s after ``ready`` paid 7,723 ms of send-prep
(cpu 7,390) — this process's own cold tool and plugin imports — while the
worker's prewarm build ran 6.3 s; the sequential prewarm had not reached the
provider warm yet. Plan:
``docs/agent-runtime-harness/planned/prewarm-agents-readiness-cold-2026-10-26.md``.

Named sabotage: drop ``_start_concurrent_provider_warm()`` from
``_prewarm_read_model_snapshot_in_worker`` → the warm does not run during the
build (red).
"""

from __future__ import annotations

import threading

import pytest

from hermes_cli.harness_parts.serve import boot


@pytest.fixture
def staged(monkeypatch):
    boot._reset_concurrent_provider_warm_for_tests()
    warm_ran = threading.Event()
    calls: list[str] = []
    seen: dict[str, bool] = {}

    def warm():
        calls.append("warm")
        warm_ran.set()

    def build():
        # The cold build: does the provider warm run while it does?
        seen["during_build"] = warm_ran.wait(timeout=3.0)

    monkeypatch.setattr(boot, "_provider_warm_steps", warm)
    monkeypatch.setattr(boot, "_prewarm_read_model_snapshot", build)
    yield calls, seen
    boot._reset_concurrent_provider_warm_for_tests()


def test_a_worker_bound_build_runs_beside_the_provider_warm(staged, monkeypatch):
    calls, seen = staged
    monkeypatch.setattr("agent_runtime.snapshot_worker.executor.bind", lambda: True)

    boot._prewarm_read_model_snapshot_in_worker()
    boot._prewarm_provider_runtime()  # the sequential step joins, never re-runs

    assert seen["during_build"] is True
    assert calls == ["warm"]


def test_an_in_process_build_keeps_the_sequential_order(staged, monkeypatch):
    """Positive control: no worker, no concurrency — the GIL case stays ordered."""

    calls, seen = staged
    monkeypatch.setattr("agent_runtime.snapshot_worker.executor.bind", lambda: False)

    boot._prewarm_read_model_snapshot_in_worker()
    assert seen["during_build"] is False
    boot._prewarm_provider_runtime()
    assert calls == ["warm"]
