"""Fork half of two ``tests/tools/test_tool_defs_memo_availability.py`` bridge cases (v0.23.1).

Upstream's ``BRIDGE`` set counts ``tool_describe`` as a Tool Search bridge tool that a session
without deferrable tools lacks. The fork's standalone ``tool_describe`` rides every non-empty
tool list (``tools.tool_defs_observability.with_tool_describe``), so it is never absent and
upstream's ``not BRIDGE & tools`` reads false. The behaviour under test is the SEARCH bridge
(``tool_search`` / ``tool_call``): these run upstream's own test bodies with that bridge, and
pin that ``tool_describe`` is present throughout.
"""

from __future__ import annotations

import pytest

from tests.tools import test_tool_defs_memo_availability as upstream
from tests.tools.test_tool_defs_memo_availability import clock, mail_state, tool_search_on  # noqa: F401 (fixtures)

_SEARCH_BRIDGE = frozenset({"tool_search", "tool_call"})


@pytest.fixture
def search_bridge(monkeypatch):
    monkeypatch.setattr(upstream, "BRIDGE", set(_SEARCH_BRIDGE))
    built = []
    real_agent = upstream._agent

    def agent(enabled_toolsets):
        built.append(real_agent(enabled_toolsets))
        return built[-1]

    monkeypatch.setattr(upstream, "_agent", agent)
    yield built
    assert built, "the upstream body built no agent"
    for each in built:
        assert "tool_describe" in upstream._names(each.tools)


def test_search_bridge_stays_out_of_a_live_session_when_its_only_deferrable_tools_recover(
        mail_state, clock, tool_search_on, search_bridge):  # noqa: F811 (fixtures)
    upstream.test_bridge_tools_stay_out_of_a_live_session_when_its_only_deferrable_tools_recover(
        mail_state, clock, tool_search_on)


def test_pin_restore_in_the_same_process_keeps_the_pinned_search_bridge_through_an_outage(
        mail_state, clock, tool_search_on, search_bridge, tmp_path):  # noqa: F811 (fixtures)
    upstream.test_pin_restore_in_the_same_process_keeps_the_pinned_bridge_through_an_outage(
        mail_state, clock, tool_search_on, tmp_path)
