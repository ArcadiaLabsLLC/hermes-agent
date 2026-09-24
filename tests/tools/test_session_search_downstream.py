"""Fork-owned tests moved out of ``tests/tools/test_session_search.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from tools.session_search_tool import (
    SESSION_SEARCH_SCHEMA,
)


class TestSchema:
    # Fork-retained (T6b): the wire description is a brief; the full text lives
    # in the fork-owned tools.tool_full_descriptions mirror that tool_describe
    # serves. Upstream pruned these; they guard the fork's trim, so they stay.
    # (test_sort_enum dropped — upstream's test_schema_params_cover_every_shape
    # above now asserts the same enum.)
    def test_schema_description_teaches_scroll(self):
        """T6b: the wire brief names the calling shapes compactly; the detailed
        scroll mechanics are preserved in the full docs (served via
        tool_describe from the fork-owned mirror)."""
        desc = SESSION_SEARCH_SCHEMA["description"].lower()
        assert "scroll" in desc
        assert "discover" in desc
        from tools.tool_full_descriptions import full_tool_description
        full = full_tool_description("session_search")
        assert "SCROLL" in full and "DISCOVERY" in full and "BROWSE" in full
        assert "scroll FORWARD" in full or "messages[-1]" in full

    def test_schema_description_enforces_source_first_limit(self):
        """T6b: the SOURCE-FIRST caveat is compressed to one wire clause; the
        full SOURCE-FIRST LIMIT block is preserved in the full docs."""
        desc = SESSION_SEARCH_SCHEMA["description"].lower()
        # Compressed disambiguator survives on the wire.
        assert "history" in desc
        assert "live source" in desc or "inspect that first" in desc
        from tools.tool_full_descriptions import full_tool_description
        full = full_tool_description("session_search").lower()
        assert "source-first limit" in full
        assert "conversation history only" in full
        assert "session_search as secondary" in full
        assert "not found" in full
