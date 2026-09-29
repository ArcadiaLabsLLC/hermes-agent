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
    """A fenced defect under tests/hermes_cli/ must not become a burial: the
    conftest banner still fires for an XFAILED node. No row is open today (the
    test_telegram_parity fence retired 2026-09-29), so the tracker is handed
    one for the duration of the test.
    """

    def test_an_xfailed_known_defect_still_reaches_the_banner(self, monkeypatch):
        """An xfail is reported as ``skipped`` + ``wasxfail``, never ``failed``.

        The pre-ML-16 classifier matched ``failed`` only, so adding the mark
        would have made the KNOWN DEFECTS section stop printing — the defect
        fenced AND unexplained.
        """
        recorded: list[str] = []
        monkeypatch.setattr(package_conftest._KNOWN_DEFECT_TRACKER, "failures", recorded)
        monkeypatch.setattr(
            package_conftest._KNOWN_DEFECT_TRACKER, "_known", {"test_commands.py": "row"}
        )
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
