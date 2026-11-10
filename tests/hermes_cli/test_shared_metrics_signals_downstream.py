"""Fork half of upstream's two ``browser_exec`` tool-unavailable cases in
``tests/hermes_cli/test_shared_metrics_signals.py``.

Upstream v0.23.1 (6393828580) anchors "a shipped built-in the session lacks is reported"
on ``browser_exec`` in a session that never narrowed its toolsets. Upstream's tool_search
scope holds deferred names only, so an eager ``browser_exec`` reads as missing. The fork
widens that scope to every name the session really carries, eager too
(``tools.tool_search_downstream.admit_direct_in_scope``), so an available ``browser_exec``
is in the session and correctly not reported. The upstream ids carry an xfail row in
``tests/_downstream/id_markers/fork_marks.py``; here the same assertions run on a session
that really lacks ``browser_exec`` (its toolsets disabled).

Killing mutation (applied, red recorded, reverted): drop the
``_tool_search_scoped_names`` check from ``shared_metrics_signals.tool_unavailable_fields``
-> the deferred ``session_search`` control below reds.
"""

from __future__ import annotations

from types import SimpleNamespace

from hermes_cli.observability import shared_metrics_contract as contract
from hermes_cli.observability import shared_metrics_signals as signals
from tests.hermes_cli.test_shared_metrics_signals import marks  # noqa: F401  upstream fixture

_WITHOUT_BROWSER = ["browser", "browser-use"]


def _session(**extra):
    return SimpleNamespace(_delegate_depth=0, enabled_toolsets=None, disabled_toolsets=_WITHOUT_BROWSER, **extra)


def test_a_builtin_the_session_disabled_is_reported_and_one_it_carries_is_not(monkeypatch):
    monkeypatch.setattr("tools.skill_provenance.is_background_review", lambda: False)
    route = {"model": "m", "provider": "openrouter"}
    fields = signals.tool_unavailable_fields(_session(), "browser_exec", "unknown_tool", route)
    assert fields == {"model": "m", "provider": "openrouter", "tool_name": "browser_exec"}
    assert contract.counter_dimensions_are_valid(contract.TOOL_UNAVAILABLE_METRIC, fields)
    # Deferred behind tool_search, so reachable: not unavailable.
    assert signals.tool_unavailable_fields(_session(), "session_search", "unknown_tool", route) is None
    assert signals.tool_unavailable_fields(_session(), "mcp_github_search", "unknown_tool", route) is None
    assert signals.tool_unavailable_fields(_session(), "browser_exec", "invalid_json", route) is None


def test_turn_validation_reports_the_disabled_builtin_once_and_unknown_names_never(marks, monkeypatch):  # noqa: F811
    from hermes_cli.observability.shared_metrics_model import record_tool_call_quality

    monkeypatch.setattr("tools.skill_provenance.is_background_review", lambda: False)
    agent = _session(provider="openrouter", model="anthropic/claude-sonnet-4", valid_tool_names={"memory"}, tools=[])
    calls = [SimpleNamespace(function=SimpleNamespace(name=n, arguments="{}"))
             for n in ("browser_exec", "memory", "my_plugin_tool")]
    record_tool_call_quality(agent, calls, set())
    unavailable = [d for m, d in marks.rows if m == contract.TOOL_UNAVAILABLE_MARK]
    assert unavailable == [{"model": unavailable[0]["model"], "provider": "openrouter", "tool_name": "browser_exec"}]
    assert contract.counter_dimensions_are_valid(contract.TOOL_UNAVAILABLE_METRIC, unavailable[0])
