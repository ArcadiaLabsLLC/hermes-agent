"""Fork-owned tests moved out of ``tests/tools/test_session_search.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from tools.session_search_tool import (
    SESSION_SEARCH_SCHEMA,
)


class TestSchema:
    # Fork-retained (T6b): the wire description is a brief that the eternia-harness
    # llm_request middleware swaps in (tools.downstream_schema); the registry keeps
    # upstream's full text, which tool_describe serves.
    def test_schema_description_teaches_scroll(self):
        """T6b: the wire brief names the calling shapes compactly; the scroll
        mechanics stay in upstream's full text (served via tool_describe)."""
        from tools.downstream_schema import BRIEF_DESCRIPTIONS

        brief = BRIEF_DESCRIPTIONS["session_search"].lower()
        assert "scroll" in brief
        assert "discover" in brief
        full = SESSION_SEARCH_SCHEMA["description"]
        assert "scroll" in full and "discovery" in full and "browse" in full
        assert "around_message_id" in full

    def test_schema_description_enforces_source_first_limit(self):
        """T6b: the source-first caveat is compressed to one wire clause; upstream's
        full text keeps it."""
        from tools.downstream_schema import BRIEF_DESCRIPTIONS

        brief = BRIEF_DESCRIPTIONS["session_search"].lower()
        assert "history" in brief
        assert "live source" in brief or "inspect that first" in brief
        full = SESSION_SEARCH_SCHEMA["description"].lower()
        assert "conversation history only" in full
        assert "inspect that first" in full
        assert "not found" in full


def test_persona_chat_scratch_rides_an_upstream_hidden_source():
    """The persona chat's raw scratch lineage must never be recall-reachable; it uses
    upstream's hidden ``tool`` source rather than a fork entry in the hidden list."""
    from agent_runtime.persona_runtime import PERSONA_CHAT_SCRATCH_SOURCE
    from tools.session_search_tool import _HIDDEN_SESSION_SOURCES

    assert PERSONA_CHAT_SCRATCH_SOURCE in _HIDDEN_SESSION_SOURCES
