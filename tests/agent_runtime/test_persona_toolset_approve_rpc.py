"""``runtime.persona.toolset.approve`` — the one write path of the bundled opt-in record (B3).

Plan bundled-shell-family-opt-in-2026-10-21.md. Killing mutation: let the Developer Edition write
(drop ``write_approval``'s edition check) -> the ``edition_not_bundled`` test reds.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import bundled_toolsets as bt
from agent_runtime.serve_rpc import console_operations as rpc
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS
from agent_runtime.serve_rpc.registry import method_tier


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    from agent_runtime.store import AgentStore

    monkeypatch.setattr(AgentStore, "get", lambda self, pid: SimpleNamespace(id=pid, hermes_profile=None))
    monkeypatch.setattr(bt, "persona_home", lambda _persona: tmp_path)
    monkeypatch.setattr(bt, "profile_name", lambda: bt.DESKTOP_PROFILE)
    return tmp_path


def _edition(monkeypatch, bundled: bool) -> None:
    monkeypatch.setattr("hermes_cli.steward.is_bundled_payload", lambda _root: bundled)


def _call(mode: str, toolset: str = "terminal") -> dict:
    return rpc.toolset_approve("r", {"persona_id": "neko", "toolset": toolset, "mode": mode, "reason": "site"})


def test_grant_then_revoke_reports_the_persona_s_approvals(home, monkeypatch):
    _edition(monkeypatch, True)
    granted = _call("grant")
    assert granted["result"]["toolset_approvals"] == ["terminal"], granted
    assert "terminal" not in bt.bundled_disabled_toolsets(SimpleNamespace(id="neko", hermes_profile=None))
    assert _call("revoke")["result"]["toolset_approvals"] == []
    assert method_tier("runtime.persona.toolset.approve") == "console"


def test_the_developer_edition_is_refused_and_writes_nothing(home, monkeypatch):
    _edition(monkeypatch, False)
    reply = _call("grant")
    assert reply["error"]["code"] == ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "edition_not_bundled"
    assert not (home / "approvals").exists()


def test_a_refused_toolset_and_a_bad_mode_are_typed(home, monkeypatch):
    _edition(monkeypatch, True)
    assert _call("grant", "discord")["error"]["data"]["reason"] == "toolset_no_platform"
    assert _call("allow")["error"]["code"] == ERR_INVALID_PARAMS
