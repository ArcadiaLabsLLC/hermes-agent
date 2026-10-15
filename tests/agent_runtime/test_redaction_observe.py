from agent_runtime.progress import _safe_progress_payload


def test_observe_mode_keeps_suppressed_progress_payload_with_marker(monkeypatch):
    monkeypatch.setenv("HERMES_REDACTION_MODE", "observe")

    payload = _safe_progress_payload(
        "run.progress",
            {
                "raw_model_output": "ordinary operator-visible output",
                "command_label": "curl -H API_KEY=abcdef1234567890",
            },
        )

    assert payload["raw_model_output"] == "ordinary operator-visible output"
    assert "[redacted line" in payload["command_label"]
    assert payload["would_redact"]["raw_model_output"] == "unsupported_progress_key"
    assert payload["would_redact"]["command_label"] == "command_label"


def test_observe_mode_still_masks_secret_lines(monkeypatch):
    monkeypatch.setenv("HERMES_REDACTION_MODE", "observe")

    payload = _safe_progress_payload(
        "run.progress",
        {"raw_model_output": "safe line\nAPI_KEY=abcdef1234567890\nnext line"},
    )

    assert "safe line" in payload["raw_model_output"]
    assert "[redacted line" in payload["raw_model_output"]
    assert "abcdef1234567890" not in payload["raw_model_output"]


def test_strict_mode_admits_the_tool_call_record_fields(monkeypatch):
    """The finished-call record survives with observe mode OFF (runtime-queue row, w5-rt)."""
    monkeypatch.setenv("HERMES_REDACTION_MODE", "strict")

    payload = _safe_progress_payload(
        "run.tool.finished",
        {
            "tool_call_id": "call_abc-123",
            "outcome": "timed_out",
            "timed_out": True,
            "timeout_seconds": 180,
        },
    )

    assert payload["tool_call_id"] == "call_abc-123"
    assert payload["outcome"] == "timed_out"
    assert payload["timed_out"] is True
    assert payload["timeout_seconds"] == 180
    assert "would_redact" not in payload


def test_the_tool_call_record_fields_are_type_checked_not_coerced(monkeypatch):
    monkeypatch.setenv("HERMES_REDACTION_MODE", "strict")
    bad = {
        "tool_call_id": "../etc/passwd",
        "outcome": "exploded",
        "timed_out": "yes",
        "timeout_seconds": True,
    }

    assert _safe_progress_payload("run.tool.finished", bad) == {"type": "run.tool.finished"}

    monkeypatch.setenv("HERMES_REDACTION_MODE", "observe")
    observed = _safe_progress_payload("run.tool.finished", bad)
    assert observed["would_redact"] == {key: "tool_call_field" for key in bad}
