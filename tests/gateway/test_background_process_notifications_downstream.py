"""Fork-owned tests moved out of ``tests/gateway/test_background_process_notifications.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import asyncio
from types import SimpleNamespace
import pytest
from gateway.config import Platform
from gateway.run import GatewayRunner

from tests.gateway.test_background_process_notifications import (  # noqa: F401 — upstream names the moved tests use
    _FakeRegistry,
    _build_runner,
)


class TestLoadBackgroundNotificationsMode:
    def test_env_var_overrides_config(self, monkeypatch, tmp_path):
        (tmp_path / "config.yaml").write_text(
            "display:\n  background_process_notifications: error\n"
        )
        import gateway.run as gw
        monkeypatch.setattr(gw, "_hermes_home", tmp_path)
        monkeypatch.setenv("HERMES_BACKGROUND_NOTIFICATIONS", "off")
        assert GatewayRunner._load_background_notifications_mode() == "off"

    def test_false_value_maps_to_off(self, monkeypatch, tmp_path):
        (tmp_path / "config.yaml").write_text(
            "display:\n  background_process_notifications: false\n"
        )
        import gateway.run as gw
        monkeypatch.setattr(gw, "_hermes_home", tmp_path)
        monkeypatch.delenv("HERMES_BACKGROUND_NOTIFICATIONS", raising=False)
        assert GatewayRunner._load_background_notifications_mode() == "off"


@pytest.mark.asyncio
async def test_agent_notification_sends_standalone_without_a_reply_anchor(monkeypatch, tmp_path):
    """A watcher send carries NO reply anchor, even when the watcher holds the
    arming message_id: the alert goes out standalone in its thread, as upstream
    10938a7cf9 (#52694) decided (owner ruling 2026-10-01, ``36fb9474ff`` dropped
    the fork's ``reply_to`` carry; finished background work is reported in
    Mission Control's Background Work panel)."""
    import tools.process_registry as pr_module

    sessions = [SimpleNamespace(
        output_buffer="SMOKE_OK\n", exited=True, exit_code=0, command="sleep 1",
    )]
    monkeypatch.setattr(pr_module, "process_registry", _FakeRegistry(sessions))

    async def _instant_sleep(*_a, **_kw):
        pass
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    runner = _build_runner(monkeypatch, tmp_path, "all")
    adapter = runner.adapters[Platform.TELEGRAM]

    watcher = {
        "session_id": "proc_anchor",
        "check_interval": 0,
        "session_key": "agent:main:telegram:dm:123:24296",
        "platform": "telegram",
        "chat_id": "123",
        "thread_id": "24296",
        "message_id": "555",
    }
    await runner._run_process_watcher(watcher)

    adapter.handle_message.assert_not_awaited()
    adapter.send.assert_awaited_once()
    args, kwargs = adapter.send.await_args
    assert args[0] == "123"
    assert "SMOKE_OK" in args[1]
    assert "reply_to" not in kwargs
    assert kwargs["metadata"] == {"thread_id": "24296"}


@pytest.mark.asyncio
async def test_agent_notification_no_message_id_is_tolerated(monkeypatch, tmp_path):
    """A watcher dict without message_id (CLI spawn, pre-upgrade checkpoint)
    still sends, standalone."""
    import tools.process_registry as pr_module

    sessions = [SimpleNamespace(
        output_buffer="done\n", exited=True, exit_code=0, command="sleep 1",
    )]
    monkeypatch.setattr(pr_module, "process_registry", _FakeRegistry(sessions))

    async def _instant_sleep(*_a, **_kw):
        pass
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    runner = _build_runner(monkeypatch, tmp_path, "all")
    adapter = runner.adapters[Platform.TELEGRAM]

    watcher = {
        "session_id": "proc_anchorless",
        "check_interval": 0,
        "session_key": "agent:main:telegram:dm:123:24296",
        "platform": "telegram",
        "chat_id": "123",
        "thread_id": "24296",
    }
    await runner._run_process_watcher(watcher)

    adapter.handle_message.assert_not_awaited()
    adapter.send.assert_awaited_once()
    assert "reply_to" not in adapter.send.await_args.kwargs
