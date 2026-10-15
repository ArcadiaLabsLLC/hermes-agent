"""Fork-owned half of ``tests/tools/test_tool_search_multiquery.py``.

The fork's ``tools.tool_search.dispatch_tool_describe`` returns details for a
directly-listed tool that IS in the session's assembly and rejects it only when
it is not; upstream's ``test_registered_direct_surface_name_keeps_exact_error``
(always an error) is a strict xfail row in ``tests/_downstream/id_markers/``.
``_register`` is upstream's.
"""

from __future__ import annotations

import json

from tests.tools.test_tool_search_multiquery import _register


class TestBatchedDescribe:
    def test_registered_direct_surface_has_details_only_when_in_session(self):
        from tools.tool_search import ToolSearchConfig, dispatch_tool_describe

        name = "mq_desktop_direct_action"
        tool_def = _register(name, "desktop_ui")
        result = json.loads(dispatch_tool_describe(
            {"names": [name]},
            current_tool_defs=[tool_def],
            config=ToolSearchConfig.from_raw({}),
        ))

        assert result["tools"][name]["parameters"] == tool_def["function"]["parameters"]
        hidden = json.loads(dispatch_tool_describe(
            {"names": [name]}, current_tool_defs=[], config=ToolSearchConfig.from_raw({})))
        # Wording is upstream's ``not_deferrable_error``; the fork's shape (details when the
        # tool IS in the assembly, the rejection only when it is not) is what is asserted.
        assert hidden["errors"][name] == (
            f"'{name}' is a directly-listed tool, not a deferred one. "
            "Call it directly instead of via tool_call."
        )
        assert name not in result.get("not_found", [])
