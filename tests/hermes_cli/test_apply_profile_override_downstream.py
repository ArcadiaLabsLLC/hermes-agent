"""Fork-owned tests moved out of ``tests/hermes_cli/test_apply_profile_override.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tests.hermes_cli.test_apply_profile_override import (  # noqa: F401 — upstream names the moved tests use
    _pin_hermes_root,
    _run_apply_profile_override,
)


class TestApplyProfileOverrideHermesHomeGuard:
    # Fork-retained: the Harness rebind lane (`hermes harness agent set-profile
    # <agent> --profile <name>`) must survive the early global-profile
    # pre-parser. Upstream has no harness command, so these have no upstream
    # counterpart.
    def test_harness_agent_set_profile_argument_is_not_consumed(
        self, tmp_path, monkeypatch
    ):
        """The Harness rebind target must reach its owning subcommand parser."""
        hermes_root = tmp_path / ".hermes"
        hermes_root.mkdir(parents=True, exist_ok=True)
        argv = [
            "hermes",
            "harness",
            "agent",
            "set-profile",
            "qa",
            "--profile",
            "launcher-qa",
            "--dry-run",
            "--json",
        ]

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        _pin_hermes_root(monkeypatch, hermes_root)
        monkeypatch.delenv("HERMES_HOME", raising=False)
        monkeypatch.setattr(sys, "argv", list(argv))

        from hermes_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("HERMES_HOME") is None
        assert sys.argv == argv

    def test_global_profile_is_consumed_but_harness_rebind_target_survives(
        self, tmp_path, monkeypatch
    ):
        """A global selector and the Harness target can coexist in one argv."""
        from hermes_cli import profiles

        monkeypatch.setattr(
            profiles,
            "resolve_profile_env",
            lambda name: str(tmp_path / ".hermes" / "profiles" / name),
        )
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            hermes_home=None,
            active_profile="base",
            argv=[
                "hermes",
                "--profile",
                "base",
                "harness",
                "agent",
                "set-profile",
                "qa",
                "--profile",
                "launcher-qa",
                "--dry-run",
                "--json",
            ],
        )

        assert result is not None
        assert result.endswith("base")
        assert sys.argv == [
            "hermes",
            "harness",
            "agent",
            "set-profile",
            "qa",
            "--profile",
            "launcher-qa",
            "--dry-run",
            "--json",
        ]


def test_extracted_profile_scanner_normalizes_and_preserves_rebind(monkeypatch):
    from hermes_cli import _profile_bootstrap as bootstrap
    monkeypatch.setattr(sys, "argv", ["hermes"])
    assert bootstrap._scan_profile_flag(["-p", " Work ", "chat"]) == ("work", 2, 0)
    assert bootstrap._scan_profile_flag(["--profile= Work ", "chat"]) == ("work", 1, 0)
    assert bootstrap._scan_profile_flag(["harness", "agent", "set-profile", "--profile", "work"]) == (None, 0, None)


def test_extracted_profile_scanner_distinguishes_cli_typos_from_pytest(monkeypatch, capsys):
    import pytest
    from hermes_cli import _profile_bootstrap as bootstrap
    monkeypatch.setattr(sys, "argv", ["hermes"])
    with pytest.raises(SystemExit) as error:
        bootstrap._scan_profile_flag(["-p", "Work Bot", "chat"])
    assert error.value.code == 2
    assert "hermes profile list" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["pytest"])
    assert bootstrap._scan_profile_flag(["-p", "Work Bot"]) == (None, 0, None)
    assert bootstrap._scan_profile_flag(["-p", "no:xdist"]) == (None, 0, None)
    assert capsys.readouterr().err == ""
