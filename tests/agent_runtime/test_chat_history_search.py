"""``runtime.persona.chat.history.search``: hits in unloaded history open through the history read (L5.05)."""
from contextlib import closing

from agent_runtime import serve_rpc
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS
from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import fixture


def _rpc(method, params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "search", "method": method, "params": params})


def _search(params):
    return _rpc("runtime.persona.chat.history.search", params)


def _seed(tmp_path, monkeypatch, rows):
    target = fixture(tmp_path / "home", monkeypatch, "Test")
    with closing(SessionDB(tmp_path / "home" / "state.db")) as db:
        for role, text in rows:
            db.append_message(target["session_id"], role, text, **({"tool_call_id": "c1", "tool_name": "x"}
                                                                     if role == "tool" else {}))
    return target


def test_a_hit_beyond_the_newest_page_opens_through_the_history_read(tmp_path, monkeypatch):
    rows = [("assistant", "The blue 鍵 needle is under the mat.")]
    rows += [("user" if i % 2 == 0 else "assistant", f"filler {i}") for i in range(45)]
    target = _seed(tmp_path, monkeypatch, rows)
    newest = _rpc("runtime.persona.chat.history", {"session_id": target["session_id"]})["result"]
    assert not any("needle" in row["text"] for row in newest["messages"])  # not in the loaded page

    found = _search({"session_id": target["session_id"], "query": "NEEDLE 鍵"})["result"]
    assert found["count"] == 1 and found["has_more"] is False
    hit = found["hits"][0]
    assert "blue 鍵 needle" in hit["snippet"] and hit["role"] == "agent"
    opened = _rpc("runtime.persona.chat.history",
                  {"session_id": target["session_id"], "before": hit["open_before"]})["result"]
    assert opened["messages"][-1]["id"] == hit["id"]
    assert "needle" in opened["messages"][-1]["text"]


def test_every_term_must_match_and_a_miss_is_an_ok_empty_page(tmp_path, monkeypatch):
    target = _seed(tmp_path, monkeypatch, [("assistant", "alpha beta"), ("assistant", "alpha gamma")])
    assert _search({"session_id": target["session_id"], "query": "alpha gamma"})["result"]["count"] == 1
    missed = _search({"session_id": target["session_id"], "query": "alpha delta"})["result"]
    assert missed["ok"] is True and missed["count"] == 0 and missed["hits"] == []


def test_hits_page_newest_first_and_the_cursor_continues_to_older_ones(tmp_path, monkeypatch):
    target = _seed(tmp_path, monkeypatch, [("assistant", f"pager {i}") for i in range(3)])
    seen = []
    params = {"session_id": target["session_id"], "query": "pager", "limit": 2}
    page = _search(params)["result"]
    seen += [hit["snippet"] for hit in page["hits"]]
    assert page["has_more"] is True
    page = _search({**params, "before": page["next_before"]})["result"]
    seen += [hit["snippet"] for hit in page["hits"]]
    assert page["has_more"] is False and page["next_before"] is None
    assert seen == ["pager 2", "pager 1", "pager 0"]


def test_text_the_history_read_does_not_show_is_never_a_hit(tmp_path, monkeypatch):
    target = _seed(tmp_path, monkeypatch, [("tool", "secret-tool-only-token result")])
    assert _search({"session_id": target["session_id"], "query": "secret-tool-only-token"})["result"]["count"] == 0


def test_bad_requests_are_typed_refusals(tmp_path, monkeypatch):
    target = _seed(tmp_path, monkeypatch, [])
    for params in ({"session_id": target["session_id"]}, {"session_id": target["session_id"], "query": "   "},
                   {"session_id": target["session_id"], "query": "x", "limit": True}):
        refused = _search(params)["error"]
        assert refused["code"] == ERR_INVALID_PARAMS and refused["data"]["reason"] == "invalid_request"
    foreign = _search({"session_id": target["session_id"], "query": "x", "before": "bm90LWEtY3Vyc29y"})["error"]
    assert foreign["data"]["reason"] == "invalid_history_cursor"
