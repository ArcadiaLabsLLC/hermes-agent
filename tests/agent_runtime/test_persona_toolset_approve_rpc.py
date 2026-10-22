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


# ``runtime.persona.toolset.list`` — the approve verb's read (RT-PERSONA-TOOLSET-APPROVALS-READ).
# Killing mutation: answer ``granted`` from the profile's list instead of the record -> the not-granted test reds.


def _list(persona_id: str = "neko") -> dict:
    return rpc.toolset_list("r", {"persona_id": persona_id})


def _offer(reply: dict, toolset: str = "terminal") -> dict:
    return next(row for row in reply["result"]["toolsets"] if row["toolset"] == toolset)


def test_list_reports_a_granted_toolset(home, monkeypatch):
    _edition(monkeypatch, True)
    _call("grant")
    reply = _list()
    assert reply["result"]["edition_not_bundled"] is False and reply["result"]["persona_id"] == "neko"
    assert _offer(reply) == {"toolset": "terminal", "granted": True}
    assert method_tier("runtime.persona.toolset.list") == "console"


def test_list_reports_an_offered_toolset_not_granted(home, monkeypatch):
    _edition(monkeypatch, True)
    reply = _list()
    assert _offer(reply) == {"toolset": "terminal", "granted": False}
    assert "discord" not in {row["toolset"] for row in reply["result"]["toolsets"]}  # no platform: not offered
    assert not any(row["granted"] for row in reply["result"]["toolsets"])


def test_list_on_the_developer_edition_offers_nothing(home, monkeypatch):
    _edition(monkeypatch, False)
    assert _list()["result"] == {"persona_id": "neko", "edition_not_bundled": True, "toolsets": []}


def test_list_for_an_unknown_persona_is_refused(home, monkeypatch):
    from agent_runtime.store import AgentStore

    def missing(self, pid):
        raise KeyError(pid)

    _edition(monkeypatch, True)
    monkeypatch.setattr(AgentStore, "get", missing)
    reply = _list("ghost")
    assert reply["error"]["code"] == ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "persona_not_found"
    assert _list("")["error"]["code"] == ERR_INVALID_PARAMS
