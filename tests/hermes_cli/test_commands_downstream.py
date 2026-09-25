"""Fork-owned tests moved out of ``tests/hermes_cli/test_commands.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from tests._downstream import hermes_cli_conftest as package_conftest
from tests._downstream.hermes_cli_conftest import hooks as conftest_hooks
import hermes_cli.commands_platforms as commands_module
from hermes_cli.commands_platforms import _SLACK_RESERVED_COMMANDS, _SLACK_VIA_HERMES_ONLY, slack_native_slashes
from hermes_cli.commands_platforms import slack_clamped_slashes

# Imported as a module, not by name: a ``Test*`` class bound here would be
# collected a second time, and this file defines its own TestSlackNativeSlashes.
from tests.hermes_cli import test_commands as _upstream_test_commands


class TestSlackNativeSlashes:
    def test_clamped_commands_are_named_not_silently_dropped(self, monkeypatch, caplog):
        """Slack's app cap must never cost coverage silently.

        The 50 is SLACK'S limit (an app may register at most 50 slash
        commands), not a Hermes tuning knob — so the answer to a full registry
        is curation, not a bigger number. But an unaccounted clamp made "which
        commands keep a native slash" a function of how many plugins happen to
        be installed, discoverable only by diffing generated manifests.

        Driven off a forced small cap so the pin is deterministic rather than
        a function of the installed plugin set.
        """
        monkeypatch.setattr(commands_module, "_SLACK_MAX_SLASH_COMMANDS", 5)

        with caplog.at_level(logging.WARNING, logger="hermes_cli.commands"):
            entries = slack_native_slashes()
        clamped = slack_clamped_slashes()
        names = {name for name, _d, _h in entries}

        assert len(entries) == 5
        assert clamped, "a cap of 5 must drop commands"
        # Accounting agrees with the list it accounts for.
        assert not (set(clamped) & names)

        warnings = [
            record.getMessage()
            for record in caplog.records
            if record.levelno >= logging.WARNING
            and record.name == "hermes_cli.commands"
        ]
        assert len(warnings) == 1, warnings
        message = warnings[0]
        assert str(len(clamped)) in message
        for name in clamped:
            assert f"/{name}" in message, f"{name!r} dropped without being named"

    def test_no_clamp_report_when_everything_fits(self, monkeypatch, caplog):
        """Control: the report is caused by the clamp, not emitted always."""
        monkeypatch.setattr(commands_module, "_SLACK_MAX_SLASH_COMMANDS", 10_000)

        with caplog.at_level(logging.WARNING, logger="hermes_cli.commands"):
            slack_native_slashes()

        assert slack_clamped_slashes() == []
        assert not [
            record for record in caplog.records
            if record.levelno >= logging.WARNING
            and record.name == "hermes_cli.commands"
        ]

    def test_clamp_report_excludes_deliberate_skips(self, monkeypatch):
        """Curated omissions are not clamp casualties.

        Slack built-ins and ``_SLACK_VIA_HERMES_ONLY`` entries are deliberate
        decisions with their own comments; reporting them as cap casualties
        would bury the names that really did lose a slot to the cap.
        """
        monkeypatch.setattr(commands_module, "_SLACK_MAX_SLASH_COMMANDS", 5)
        clamped = set(slack_clamped_slashes())

        assert not (clamped & set(_SLACK_RESERVED_COMMANDS))
        assert not (clamped & set(_SLACK_VIA_HERMES_ONLY))


class TestKnownDefectFence:
    """The fence around ``test_telegram_parity`` must not become a burial.

    Two things have to hold together, and they fail in opposite directions:
    the mark must be STRICT (or the defect could be silently fixed, or worse,
    silently "fixed" by a mutant, with nobody told), and the conftest banner
    must still fire for an XFAILED node (or fencing the defect would have
    retired the only place it is explained).
    """

    def test_the_parity_defect_is_fenced_strict(self):
        """Asked of the hook that applies it, not of a decorator: the upstream
        file carries no mark since lane CARRY, the id table does."""
        from tests._downstream import id_markers

        node = (
            "tests/hermes_cli/test_commands.py"
            "::TestSlackNativeSlashes::test_telegram_parity"
        )
        applied: list = []
        item = SimpleNamespace(nodeid=node, add_marker=applied.append)
        config = SimpleNamespace(args=[node], rootpath=Path.cwd())
        id_markers.pytest_collection_modifyitems(config, [item])

        marks = [mark for mark in applied if mark.name == "xfail"]
        assert len(marks) == 1
        assert marks[0].kwargs["strict"] is True
        # Single-sourced, not restated: the mark carries the conftest's text.
        assert (
            marks[0].kwargs["reason"]
            is package_conftest.TELEGRAM_PARITY_DEFECT_REASON
        )
        # The upstream test itself stays byte-identical to upstream's.
        assert not getattr(
            _upstream_test_commands.TestSlackNativeSlashes.test_telegram_parity,
            "pytestmark",
            [],
        )

    def test_an_xfailed_known_defect_still_reaches_the_banner(self, monkeypatch):
        """An xfail is reported as ``skipped`` + ``wasxfail``, never ``failed``.

        The pre-ML-16 classifier matched ``failed`` only, so adding the mark
        would have made the KNOWN DEFECTS section stop printing — the defect
        fenced AND unexplained.
        """
        recorded: list[str] = []
        monkeypatch.setattr(conftest_hooks, "_KNOWN_DEFECT_FAILURES", recorded)
        node = (
            "tests/hermes_cli/test_commands.py"
            "::TestSlackNativeSlashes::test_telegram_parity"
        )

        package_conftest.pytest_runtest_logreport(
            SimpleNamespace(
                when="call", outcome="skipped", nodeid=node, wasxfail="reason"
            )
        )
        assert recorded == [node]

        # A strict XPASS arrives as `failed` with no `wasxfail` — the day the
        # defect is really gone, the banner must name it so the row is deleted.
        package_conftest.pytest_runtest_logreport(
            SimpleNamespace(when="call", outcome="failed", nodeid=node)
        )
        assert recorded == [node, node]

        # Control: an ordinary pass in the same file is not a defect report.
        package_conftest.pytest_runtest_logreport(
            SimpleNamespace(
                when="call",
                outcome="passed",
                nodeid=(
                    "tests/hermes_cli/test_commands.py"
                    "::TestSlackAppManifest::test_btw_is_in_manifest"
                ),
            )
        )
        assert recorded == [node, node]
