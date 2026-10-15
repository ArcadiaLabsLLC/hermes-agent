from agent_runtime.skill_activity import skill_load_evidence, skill_load_history


def test_only_successful_instruction_loads_count_as_evidence():
    assert skill_load_evidence("skill_view", {"name": "example"})["status"] == "loading"
    assert skill_load_evidence("skill_view", {"name": "example"}, result={"success": False},
                               finished=True)["status"] == "failed"
    assert skill_load_evidence("read_file", {"name": "example"}) is None
    assert skill_load_evidence("skill_view", {"name": "example", "file_path": "notes.md"}) is None
    history = [
        {"role": "assistant", "content": "I used imaginary", "tool_calls": [
            {"id": "a", "function": {"name": "skill_view", "arguments": '{"name":"example"}'}},
            {"id": "b", "function": {"name": "skill_view", "arguments": '{"name":"failed"}'}},
        ]},
        {"role": "tool", "tool_call_id": "a", "content": '{"success":true,"content":"instructions"}'},
        {"role": "tool", "tool_call_id": "b", "content": '{"success":false}'},
    ]
    assert skill_load_history(history) == [{"id": "example", "count": 1}]
