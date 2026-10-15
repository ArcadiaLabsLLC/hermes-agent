"""Fork-owned tests moved out of ``tests/e2e/test_platform_commands.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import time
from types import SimpleNamespace
import pytest
from tests.e2e.conftest import make_event, send_and_capture


class TestSlashCommands:
    @pytest.mark.asyncio
    async def test_queue_status_shows_idle_visibility(self, adapter, platform):
        send = await send_and_capture(adapter, "/queue-status", platform)

        send.assert_called_once()
        response_text = send.call_args[1].get("content") or send.call_args[0][1]
        response_lower = response_text.lower()
        assert "gateway queue/status" in response_lower
        assert "active agents: 0" in response_lower
        assert "pending follow-up slot: 0" in response_lower
        assert "explicit /queue depth: 0" in response_lower
        assert f"{platform.value}: connected" in response_lower

    @pytest.mark.asyncio
    async def test_queue_status_bypasses_active_agent_and_shows_depths(
        self, adapter, runner, session_entry, platform
    ):
        session_key = session_entry.session_key
        runner._running_agents[session_key] = SimpleNamespace(
            session_id=session_entry.session_id,
            model="e2e/model",
            get_activity_summary=lambda: {
                "seconds_since_activity": 1,
                "last_activity_desc": "test",
                "api_call_count": 1,
                "max_iterations": 10,
            },
            interrupt=lambda _text: None,
        )
        runner._running_agents_ts[session_key] = time.time() - 125
        adapter._pending_messages[session_key] = make_event(platform, "queued head")
        runner._queued_events[session_key] = [
            make_event(platform, "queued tail 1"),
            make_event(platform, "queued tail 2"),
        ]

        send = await send_and_capture(adapter, "/qstatus", platform)

        send.assert_called_once()
        response_text = send.call_args[1].get("content") or send.call_args[0][1]
        response_lower = response_text.lower()
        assert "active agents: 1" in response_lower
        assert "current session: running" in response_lower
        assert "running age:" in response_lower
        assert "pending follow-up slot: 1" in response_lower
        assert "explicit /queue depth: 3" in response_lower
        assert "overflow queue depth: 2" in response_lower
        runner._handle_message_with_agent.assert_not_awaited()
