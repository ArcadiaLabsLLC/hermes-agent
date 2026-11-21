import json

from agent_runtime.conversations.projection import event_frames


def frames(kind, **payload):
    return list(event_frames({"method": "event", "params": {
        "session_id": "native-a", "type": kind, "payload": payload}}))


def test_tool_output_is_not_replayed_but_actual_skill_result_is():
    result = frames("tool.complete", name="skill_view", tool_id="load", args={"name": "review"},
                    result=json.dumps({"success": True, "body": "sensitive-tool-output" * 90000}))
    assert len(json.dumps(result)) < 1000
    assert result[0]["skill_load"] == {"call_id": "load", "id": "review", "status": "loaded"}
    assert "sensitive-tool-output" not in json.dumps(result)
    assert "skill_load" not in frames("tool.complete", name="other", tool_id="x", args={"name": "review"})[0]


def test_reasoning_preserved():
    projected = frames("message.complete", text="answer", reasoning="explanation", status="complete")
    assert [(f["params"]["type"], f["params"]["payload"]["text"]) for f in projected] == [
        ("reasoning.available", "explanation"), ("message.complete", "answer")]
