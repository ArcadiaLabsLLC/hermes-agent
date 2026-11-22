"""The bundled edition's toolset refusal and the per-agent approval record (RT-NAMESPACE-SHARED-CONFIG-SHELL-FAMILY B1).

Plan ``docs/agent-runtime-harness/archive/bundled-shell-family-opt-in-2026-10-21.md``. The edition is
faked by patching ``hermes_cli.steward.is_bundled_payload`` (the build-stamp predicate).

Killing mutation: return the profile's list on the Developer Edition too -> the Developer test reds.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import bundled_toolsets as bt

SHELL = {"terminal", "code_execution", "browser", "browser-use"}


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(bt, "profile_name", lambda: bt.DESKTOP_PROFILE)
    return tmp_path


def _edition(monkeypatch, bundled: bool) -> None:
    monkeypatch.setattr("hermes_cli.steward.is_bundled_payload", lambda _root: bundled)


def _persona():
    return SimpleNamespace(id="p1", hermes_profile=None)


def test_the_developer_edition_disables_nothing(home, monkeypatch):
    _edition(monkeypatch, False)
    assert bt.bundled_disabled_toolsets(_persona()) == ()


def test_the_bundled_edition_with_no_record_disables_the_profile_list(home, monkeypatch):
    _edition(monkeypatch, True)
    disabled = bt.bundled_disabled_toolsets(_persona())
    assert disabled == bt.bundled_profile().disabled_toolsets
    assert SHELL <= set(disabled)


def test_a_granted_toolset_leaves_the_list_and_a_revoke_restores_it(home, monkeypatch):
    _edition(monkeypatch, True)
    record = bt.write_approval(home, "terminal", mode="grant", reason="build the site", granted_by="operator")
    row = record["approvals"][0]
    assert record["schema_version"] == 1
    assert {k: row[k] for k in ("toolset", "granted_by", "edition", "reason")} == {
        "toolset": "terminal", "granted_by": "operator", "edition": "bundled", "reason": "build the site"}
    on_disk = json.loads((home / "approvals" / "toolsets.json").read_text(encoding="utf-8"))
    assert on_disk == record
    disabled = bt.bundled_disabled_toolsets(_persona())
    assert "terminal" not in disabled and (SHELL - {"terminal"}) <= set(disabled)
    bt.write_approval(home, "terminal", mode="revoke")
    assert "terminal" in bt.bundled_disabled_toolsets(_persona())


@pytest.mark.parametrize(("toolset", "reason"), [
    ("discord", bt.Reason.TOOLSET_NO_PLATFORM),
    ("kanban", bt.Reason.TOOLSET_NOT_OPT_IN),
])
def test_a_grant_outside_the_opt_in_family_is_refused(home, monkeypatch, toolset, reason):
    _edition(monkeypatch, True)
    with pytest.raises(bt.ToolsetApprovalRefused) as refused:
        bt.write_approval(home, toolset, mode="grant")
    assert refused.value.reason is reason
    assert not (home / "approvals" / "toolsets.json").exists()


def test_a_toolset_whose_modules_do_not_ship_is_refused(home, monkeypatch):
    _edition(monkeypatch, True)
    monkeypatch.setattr(bt, "_toolset_ships", lambda name: name != "computer_use")
    with pytest.raises(bt.ToolsetApprovalRefused) as refused:
        bt.write_approval(home, "computer_use", mode="grant")
    assert refused.value.reason is bt.Reason.TOOLSET_NOT_SHIPPED


def test_the_developer_edition_writes_no_record(home, monkeypatch):
    _edition(monkeypatch, False)
    with pytest.raises(bt.ToolsetApprovalRefused) as refused:
        bt.write_approval(home, "terminal", mode="grant")
    assert refused.value.reason is bt.Reason.EDITION_NOT_BUNDLED
    assert not (home / "approvals").exists()


def test_a_hand_edited_row_outside_the_family_is_not_honoured(home, monkeypatch):
    _edition(monkeypatch, True)
    (home / "approvals").mkdir()
    (home / "approvals" / "toolsets.json").write_text(json.dumps(
        {"schema_version": 1, "approvals": [{"toolset": "discord"}, {"toolset": "browser"}]}), encoding="utf-8")
    disabled = set(bt.bundled_disabled_toolsets(_persona()))
    assert "discord" in disabled and "browser" not in disabled
