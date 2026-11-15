from agent_runtime.mission_chat_prompts import _safe_read_soul_overlay


def test_soul_overlay_rejects_absolute_or_secret_like_paths(tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("do not read", encoding="utf-8")

    assert _safe_read_soul_overlay(str(secret)) is None
    assert _safe_read_soul_overlay(".env") is None
    assert _safe_read_soul_overlay("auth/token.md") is None
    assert _safe_read_soul_overlay("config/profile.md") is None


def test_mission_chat_recall_tools_name_the_tool_call_route():
    """RT-MISSION-CHAT-PROMPT-NAMES-SESSION-SEARCH-AS-DIRECT: the recall tools the operative rules
    name (`session_search`, `agent_chat_open`, `agent_chat_threads`) are deferred behind tool_search
    by default, so the rules say to reach them through `tool_call`, not by the bare name."""
    from agent_runtime.mission_chat_prompts import _mission_chat_operative_rules
    from tools.tool_search import ToolSearchConfig, is_deferrable_tool_name
    import tools.session_search_tool  # noqa: F401 — registration runs at import

    cfg = ToolSearchConfig.from_raw(None)
    assert is_deferrable_tool_name("session_search", cfg.effective_defer_tools, config=cfg), (
        "session_search is no longer deferred by default; the sentence may be stale")
    rules = _mission_chat_operative_rules()
    recall = rules[rules.index("search past sessions (`session_search`)"):]
    recall = recall[:recall.index("\n")]
    assert "call it through `tool_call`, never by its bare name" in recall, recall
