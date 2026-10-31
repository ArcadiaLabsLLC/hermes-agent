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


def test_composer_preloads_remain_visible_after_later_turns_without_counting_stubs_or_mentions():
    from agent_runtime.runtime_hud.envelopes import render_skill_preload_envelope, render_runtime_context_envelope

    snapshot = render_skill_preload_envelope(skill_names=["review", "testing"],
        skill_preload_content="Session instructions")
    unchanged = render_skill_preload_envelope(skill_names=["review", "testing"],
        skill_preload_content="Session instructions", delivery="unchanged")
    hud = render_runtime_context_envelope(context_id="ctx_chat", revision="hud_abc123", delivery="snapshot",
                                         situational_hud_content="Runtime")
    history = [
        {"role": "user", "content": f"Review this\n\n{snapshot}\n\n{hud}"},
        {"role": "assistant", "content": "Complete"},
        {"role": "user", "content": "Now check another file"},
        {"role": "user", "content": f"Continue\n\n{unchanged}"},
        {"role": "assistant", "content": snapshot.replace("review", "imaginary")},
        {"role": "user", "content": snapshot.replace("review", "mentioned") + " is an example"},
    ]
    assert skill_load_history(history) == [{"id": "review", "count": 1}, {"id": "testing", "count": 1}]
    assert skill_load_history([]) == []  # A different chat does not inherit these loads.
