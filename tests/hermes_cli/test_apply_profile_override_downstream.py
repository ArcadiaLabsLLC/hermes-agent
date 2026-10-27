"""Fork-owned tests moved out of ``tests/hermes_cli/test_apply_profile_override.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tests.hermes_cli.test_apply_profile_override import (  # upstream names the moved tests use
    _run_apply_profile_override,
)


def _pin_hermes_root(monkeypatch, root: Path) -> None:
    """Point the platform-native Hermes root at ``root`` on every OS.

    ``get_default_hermes_root()`` resolves through
    ``hermes_constants._get_platform_default_hermes_home()`` (``~/.hermes`` on
    POSIX, ``%LOCALAPPDATA%/hermes`` on Windows), so patching ``Path.home``
    alone would leave these tests reading the real profile store on Windows.
    Fork-owned: upstream's file dropped its copy when it went back to upstream bytes.
    """
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "_get_platform_default_hermes_home", lambda: root)


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
    from hermes_cli import main as bootstrap
    monkeypatch.setattr(sys, "argv", ["hermes"])
    assert bootstrap._scan_profile_flag(["-p", " Work ", "chat"]) == ("work", 2, 0)
    assert bootstrap._scan_profile_flag(["--profile= Work ", "chat"]) == ("work", 1, 0)
    assert bootstrap._scan_profile_flag(["harness", "agent", "set-profile", "--profile", "work"]) == (None, 0, None)


def test_extracted_profile_scanner_distinguishes_cli_typos_from_pytest(monkeypatch, capsys):
    import pytest
    from hermes_cli import main as bootstrap
    monkeypatch.setattr(sys, "argv", ["hermes"])
    with pytest.raises(SystemExit) as error:
        bootstrap._scan_profile_flag(["-p", "Work Bot", "chat"])
    assert error.value.code == 2
    assert "hermes profile list" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["pytest"])
    assert bootstrap._scan_profile_flag(["-p", "Work Bot"]) == (None, 0, None)
    assert bootstrap._scan_profile_flag(["-p", "no:xdist"]) == (None, 0, None)
    assert capsys.readouterr().err == ""


class TestBindingPinnedHome:
    """RT-PERSONA-BINDING-ENV-REPLAN: a child of a default-bound persona turn
    gets ``HERMES_HOME=<root>`` plus ``HERMES_PROFILE_PINNED=1``; the sticky
    ``active_profile`` must not re-home it."""

    def _run(self, tmp_path, monkeypatch, *, pinned: bool, argv=None):
        from hermes_cli import profiles

        monkeypatch.setattr(
            profiles, "resolve_profile_env",
            lambda name: str(tmp_path / ".hermes" / "profiles" / name),
        )
        _pin_hermes_root(monkeypatch, tmp_path / ".hermes")
        monkeypatch.delenv("HERMES_PROFILE_PINNED", raising=False)
        return _run_apply_profile_override(
            tmp_path, monkeypatch,
            hermes_home=str(tmp_path / ".hermes"), active_profile="other",
            argv=argv or ["hermes", "chat"],
            extra_env={"HERMES_PROFILE_PINNED": "1"} if pinned else None,
        )

    def test_pinned_root_ignores_active_profile(self, tmp_path, monkeypatch):
        """Kill-mutation: remove the fork ``HERMES_PROFILE_PINNED`` rung —
        ``HERMES_HOME`` becomes ``<root>/profiles/other``."""
        result = self._run(tmp_path, monkeypatch, pinned=True)
        assert result == str(tmp_path / ".hermes")
        assert os.environ["HERMES_PROFILE_RESOLUTION"] == "binding_pinned"

    def test_unpinned_root_still_follows_active_profile(self, tmp_path, monkeypatch):
        """Positive control (#22502). Kill-mutation: skip the sticky read
        whenever ``HERMES_HOME`` is set."""
        result = self._run(tmp_path, monkeypatch, pinned=False)
        assert result == str(tmp_path / ".hermes" / "profiles" / "other")
        assert os.environ["HERMES_PROFILE_RESOLUTION"] == "active_profile_marker"

    def test_explicit_flag_beats_the_pin(self, tmp_path, monkeypatch):
        result = self._run(tmp_path, monkeypatch, pinned=True, argv=["hermes", "--profile", "x", "chat"])
        assert result == str(tmp_path / ".hermes" / "profiles" / "x")
        assert os.environ["HERMES_PROFILE_RESOLUTION"] == "flag"
