"""A synthetic unreadable-store failure's downstream outcome, not historical race attribution."""
import errno
import json

import pytest
from pathlib import Path

from hermes_cli import auth
from hermes_cli.harness_parts.persona import chat_turn_message
from .test_mission_chat_budget_payload import _args, _seed, isolate_agent_runtime_root as _runtime_fixture

isolate_agent_runtime_root = pytest.fixture(_runtime_fixture.__wrapped__)


def test_unreadable_auth_store_becomes_known_pre_request_refusal(tmp_path, monkeypatch, capsys, isolate_agent_runtime_root):
    store = tmp_path / "auth.json"
    store.write_text('{"version":1,"providers":{}}', encoding="utf-8")
    before = store.read_bytes()
    original = Path.read_text
    def read(path, *args, **kw):
        if path == store:
            raise PermissionError(errno.EACCES, "fixture sharing denied")
        return original(path, *args, **kw)
    monkeypatch.setattr(Path, "read_text", read)
    class Runtime:
        def __init__(self, *args, **kw):
            pass
        def mission_chat_reply(self, *args, **kw):
            # Real auth reader, raised at runtime resolution before agent-ready.
            auth._load_auth_store(store)
            kw["agent_ready_callback"](object())
            raise RuntimeError("reader unexpectedly returned")
    _seed(monkeypatch, Runtime)
    assert chat_turn_message._cmd_mission_chat_message(_args("auth_unreadable")) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_kind"] == "chat_turn_provider_unavailable"
    assert payload["journal_state"] == "provider_refused"
    assert payload["turn_resolution_required"] is False
    assert store.read_bytes() == before
    # No operator/live auth read, writer or historical banner fault is implied.
