"""Fork-owned half of ``tests/gateway/test_api_server_active_work_drain.py``.

Upstream's ``test_api_work_still_live_at_settle_exit_is_reinterrupted`` restores
its loop-clock patch with ``monkeypatch.undo()``, which unwinds the whole shared
per-test MonkeyPatch — the root conftest's hermetic pins included — and the
fork's ``_shared_monkeypatch_pin_tripwire`` reds it. It is a skip row in
``tests/_downstream/id_markers.py``; this is the same test with the clock patch
in a scoped ``monkeypatch.context()``. Helpers are upstream's, imported by name.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run import _INTERRUPT_REASON_GATEWAY_SHUTDOWN
from tests.gateway.restart_test_helpers import make_restart_runner
from tests.gateway.test_api_server_active_work_drain import (  # noqa: F401 — upstream names the test uses
    _make_async_noop,
    _SettlingApiAdapter,
)
from tools import browser_tool_lifecycle as bt_lifecycle


class TestShutdownSettleWindow:
    @pytest.mark.asyncio
    async def test_api_work_still_live_at_settle_exit_is_reinterrupted(
        self, monkeypatch
    ):
        """A /v1/runs agent can materialize AFTER the one-shot interrupt.

        The task is counted via ``_active_run_tasks`` from admission, but
        ``_active_run_agents[run_id]`` is populated only once ``_create_agent``
        returns — an agent landing in that window missed the single interrupt
        and previously went straight to the tool-subprocess kill. The settle
        loop must re-signal when API work is still live at exit.
        """
        import tools.process_registry as _pr
        import tools.terminal_tool as _tt
        import tools.terminal_tool_lifecycle as terminal_tool_lifecycle

        runner, adapter = make_restart_runner()
        runner._restart_drain_timeout = 0.01
        adapter.disconnect = _make_async_noop()
        api = _SettlingApiAdapter(polls_to_settle=10_000)  # never settles
        runner.adapters = {Platform.TELEGRAM: adapter, Platform.API_SERVER: api}

        monkeypatch.setattr(_pr.process_registry, "kill_all", lambda task_id=None: 0)
        monkeypatch.setattr(_tt, "cleanup_all_environments", lambda: None)
        monkeypatch.setattr(terminal_tool_lifecycle, "cleanup_all_environments", lambda: None)
        monkeypatch.setattr(bt_lifecycle, "cleanup_all_browsers", lambda: None)

        # Accelerate the loop clock: each time() call advances 1s of virtual
        # time, so the 5s settle deadline expires after a handful of polls
        # instead of 5 real seconds. Relative deadline math is preserved.
        loop = asyncio.get_running_loop()
        _real_time = type(loop).time
        _skew = [0.0]

        def _fast_time(self):
            _skew[0] += 1.0
            return _real_time(self) + _skew[0]

        with monkeypatch.context() as clock_patch:
            clock_patch.setattr(type(loop), "time", _fast_time)
            with patch("gateway.status.remove_pid_file"), \
                 patch("gateway.status.publish_runtime_status"), \
                 patch("cron.scheduler.mark_job_run"):
                await runner.stop()

        # One shot from _interrupt_running_agents + one re-signal at settle
        # exit because API work was still live.
        assert api.interrupt_reasons == [
            _INTERRUPT_REASON_GATEWAY_SHUTDOWN,
            _INTERRUPT_REASON_GATEWAY_SHUTDOWN,
        ]
