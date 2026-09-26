"""Fork-owned tests moved out of ``tests/hermes_cli/test_commands.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from pathlib import Path
from types import SimpleNamespace
from tests._downstream import hermes_cli_conftest as package_conftest

# Imported as a module, not by name: a ``Test*`` class bound here would be
# collected a second time.
from tests.hermes_cli import test_commands as _upstream_test_commands


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
        monkeypatch.setattr(package_conftest._KNOWN_DEFECT_TRACKER, "failures", recorded)
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
