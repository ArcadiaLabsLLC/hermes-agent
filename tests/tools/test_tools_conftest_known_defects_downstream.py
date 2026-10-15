"""tests/tools' KNOWN DEFECTS banner survives the defect being FENCED (lane B5, 2026-09-25).

``tests/_downstream/tools_conftest.py`` used to record a known defect's report
only when it ``failed``, with no owner filter: a strict ``xfail`` on
``test_search_error_guard.py`` would have reported ``skipped`` + ``wasxfail``
and retired its own banner, and a same-named file in another directory could
have claimed a place in it. It now feeds ``tests/_env_gap_fence.KnownDefectTracker``.
"""

from __future__ import annotations

from types import SimpleNamespace

from tests._downstream import tools_conftest


def test_an_xfailed_known_defect_still_reaches_the_banner(monkeypatch):
    recorded: list[str] = []
    monkeypatch.setattr(tools_conftest._KNOWN_DEFECT_TRACKER, "failures", recorded)
    node = "tests/tools/test_search_error_guard.py::test_literal_backslash"

    tools_conftest.pytest_runtest_logreport(
        SimpleNamespace(when="call", outcome="skipped", nodeid=node, wasxfail="reason")
    )
    assert recorded == [node]

    # Control: the same basename one directory over is not this banner's.
    tools_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            when="call", outcome="failed",
            nodeid="tests/cli/test_search_error_guard.py::test_literal_backslash",
        )
    )
    assert recorded == [node]
