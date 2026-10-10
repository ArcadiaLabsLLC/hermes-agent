"""``persona tool-diff`` prints the cost layer's split, not the callable count alone (toolvis slice 4).

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md`` §0 and
§3 slice 4, ruling R1. The headline used to read ``neko_supervisor: 45 tools`` while the turn
shipped 27; it now leads with ``eager · deferred · unavailable · blocked`` and keeps the
callable-by-name count (``final_tool_count``, which the Launcher reads) in parentheses. Driven
through the REAL argparse tree, the real chat-lane bundle and the real registry.
"""

from __future__ import annotations

import json

from tests.hermes_cli.test_persona_tool_diff_declaration import (  # noqa: F401 - fixtures
    _seed_persona,
    _tool_diff,
    bound_profile_home,
    hermetic_runtime_root,
)


def test_tool_diff_prints_the_split(bound_profile_home, capsys):  # noqa: F811
    _seed_persona()

    assert _tool_diff("dev", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    surface, visibility = payload["tool_surface"], payload["tool_visibility"]
    counts = surface["counts"]
    assert surface["contract_source"] == "chat_lane_bundle", surface.get("unavailable")
    assert counts["eager"] > 0 and counts["eager"] == visibility["eager_tool_count"]
    assert visibility["deferred_tool_count"] == counts["deferred"]
    assert visibility["final_tool_count"] == 45, "R1: the callable-by-name count keeps its meaning"

    assert _tool_diff("dev") == 0
    out = capsys.readouterr().out
    head = (f"dev: {counts['eager']} eager · {counts['deferred']} deferred · "
            f"{counts['unavailable']} unavailable · {counts['blocked']} blocked (45 callable by name)")
    assert head in out, out
    # Each non-eager group names the rule that moved it.
    for state in ("deferred", "unavailable"):
        for reason in {row["reason"] for row in surface[state].values()}:
            assert f"{state} ({reason})" in out, (state, reason)
