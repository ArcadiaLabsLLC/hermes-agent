import json

import pytest

from agent_runtime.conversations.events import ConversationEvents
from agent_runtime.conversations.projection import event_frames


def frames(kind, **payload):
    return list(event_frames({"method": "event", "params": {
        "session_id": "native-a", "type": kind, "payload": payload}}))


def test_large_unicode_response_remains_exact_in_bounded_pages():
    text = "🌍中文" * 48000
    parts = frames("message.complete", text=text, status="complete", usage={"context_used": 4})
    replay = ConversationEvents()
    for part in parts:
        replay.append("turn", part)
    collected, cursor = [], 0
    while True:
        page = replay.since(cursor)
        assert len(json.dumps(page, ensure_ascii=True)) < 1024 * 1024
        assert page["truncated"] is False
        collected.extend(row["frame"]["params"]["payload"] for row in page["events"])
        cursor = page["cursor"]
        if not page["more"]:
            break
    assert "".join(p["text"] for p in collected) == text
    assert [p["part_first"] for p in collected].count(True) == 1
    assert [p["part_last"] for p in collected].count(True) == 1
    assert collected[-1]["part_last"] is True


def test_tool_output_is_not_replayed_but_actual_skill_result_is():
    result = frames("tool.complete", name="skill_view", tool_id="load", args={"name": "review"},
                    result=json.dumps({"success": True, "body": "sensitive-tool-output" * 90000}))
    assert len(json.dumps(result)) < 1000
    assert result[0]["skill_load"] == {"call_id": "load", "id": "review", "status": "loaded"}
    assert "sensitive-tool-output" not in json.dumps(result)
    assert "skill_load" not in frames("tool.complete", name="other", tool_id="x", args={"name": "review"})[0]


def test_replay_eviction_is_explicit_and_reasoning_preserved():
    replay = ConversationEvents(maximum_bytes=250)
    for n in range(10):
        replay.append("turn", {"text": str(n) * 30})
    assert replay.since(0)["truncated"] is True
    projected = frames("message.complete", text="answer", reasoning="explanation", status="complete")
    assert [(f["params"]["type"], f["params"]["payload"]["text"]) for f in projected] == [
        ("reasoning.available", "explanation"), ("message.complete", "answer")]
    with pytest.raises(ValueError):
        replay.since(True)
